import os
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

# Point the app at a throwaway data dir before it is imported.
_TMP = tempfile.mkdtemp(prefix="clipforge-test-")
os.environ["DATA_DIR"] = _TMP
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def source_video() -> Path:
    """A 40 s 16:9 test video with a tone, standing in for a real upload."""
    from app import config

    path = config.UPLOADS_DIR / "sample-source.mp4"
    if not path.exists():
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30",
             "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100", "-t", "40",
             "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)],
            check=True,
        )
    return path


def wait_job(client, job_id: str, timeout: float = 240) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "error"):
            return job
        time.sleep(0.5)
    raise TimeoutError(job_id)


def video_info(url: str) -> dict:
    from app import config, ffmpeg

    path = config.OUTPUTS_DIR / url.rsplit("/", 1)[-1]
    info = ffmpeg.probe(path)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    return {"width": v["width"], "height": v["height"], "duration": float(info["format"]["duration"]),
            "audio": any(s["codec_type"] == "audio" for s in info["streams"])}
