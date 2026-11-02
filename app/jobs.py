"""A small background job queue with progress reporting, persisted as JSON files."""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable

from . import config, ffmpeg


@dataclass
class Job:
    id: str
    kind: str
    params: dict
    status: str = "queued"  # queued | running | done | error
    progress: float = 0.0
    message: str = "Waiting in queue"
    outputs: list[dict] = field(default_factory=list)
    error: str | None = None
    created: float = field(default_factory=time.time)
    finished: float | None = None


class JobContext:
    def __init__(self, manager: "JobManager", job: Job):
        self._m = manager
        self.job = job
        self.work = config.WORK_DIR / job.id
        self.work.mkdir(parents=True, exist_ok=True)

    def update(self, progress: float | None = None, message: str | None = None) -> None:
        if progress is not None:
            self.job.progress = max(0.0, min(1.0, progress))
        if message is not None:
            self.job.message = message
        self._m.save(self.job)

    def output_path(self, suffix: str = ".mp4") -> Path:
        return config.OUTPUTS_DIR / f"{self.job.id}-{len(self.job.outputs) + 1}{suffix}"

    def add_output(self, path: Path, title: str = "", **meta) -> None:
        thumb = path.with_suffix(".jpg")
        try:
            at = min(1.0, max(ffmpeg.duration(path) / 3, 0))
            ffmpeg.run(["-ss", f"{at:.2f}", "-i", path, "-frames:v", "1", "-vf", "scale=360:-2", thumb])
        except ffmpeg.FFmpegError:
            thumb = None
        self.job.outputs.append({
            "url": f"/media/outputs/{path.name}",
            "thumbnail": f"/media/outputs/{thumb.name}" if thumb else None,
            "title": title,
            "duration": round(ffmpeg.duration(path), 2),
            **meta,
        })
        self._m.save(self.job)


class JobManager:
    def __init__(self, workers: int = config.MAX_WORKERS):
        self.jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="render")
        self._load()

    def _load(self) -> None:
        for f in sorted(config.JOBS_DIR.glob("*.json")):
            try:
                job = Job(**json.loads(f.read_text()))
            except Exception:
                continue
            if job.status in ("queued", "running"):
                job.status, job.error, job.message = "error", "Interrupted by a server restart", "Interrupted"
            self.jobs[job.id] = job

    def save(self, job: Job) -> None:
        with self._lock:
            tmp = config.JOBS_DIR / f"{job.id}.json.tmp"
            tmp.write_text(json.dumps(asdict(job)))
            tmp.replace(config.JOBS_DIR / f"{job.id}.json")

    def submit(self, kind: str, params: dict, fn: Callable[[JobContext, dict], None]) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, params=params)
        self.jobs[job.id] = job
        self.save(job)
        self._pool.submit(self._run, job, fn)
        return job

    def _run(self, job: Job, fn: Callable[[JobContext, dict], None]) -> None:
        ctx = JobContext(self, job)
        job.status = "running"
        ctx.update(0.01, "Starting")
        try:
            fn(ctx, job.params)
            job.status, job.progress, job.message = "done", 1.0, "Done"
        except Exception as e:  # report any failure to the UI
            job.status, job.error, job.message = "error", str(e) or e.__class__.__name__, "Failed"
            traceback.print_exc()
        finally:
            job.finished = time.time()
            self.save(job)
            if not os.environ.get("KEEP_WORK"):
                shutil.rmtree(ctx.work, ignore_errors=True)

    def list(self) -> list[Job]:
        return sorted(self.jobs.values(), key=lambda j: j.created, reverse=True)

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def delete(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if not job or job.status in ("queued", "running"):
            return False
        for f in config.OUTPUTS_DIR.glob(f"{job_id}-*"):
            f.unlink(missing_ok=True)
        (config.JOBS_DIR / f"{job_id}.json").unlink(missing_ok=True)
        del self.jobs[job_id]
        return True
