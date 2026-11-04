"""HTTP API + static web UI."""
from __future__ import annotations

import re
import shutil
import subprocess
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from . import captions, config, llm, media, tts
from .jobs import JobManager
from .pipelines import chat, clipper, edit, story
from .pipelines.compose import LAYOUTS
from .render import images

STATIC = config.ROOT / "app" / "static"
jobs: JobManager | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global jobs
    missing = [tool for tool in ("ffmpeg", "ffprobe") if not shutil.which(tool)]
    if missing:
        raise SystemExit(
            f"\n\n  {' and '.join(missing)} not found. ClipForge needs ffmpeg to make videos.\n"
            "  Install it, then start the app again:\n"
            "    Mac:     brew install ffmpeg\n"
            "    Windows: winget install Gyan.FFmpeg   (then open a new terminal)\n"
            "    Linux:   sudo apt install ffmpeg\n")
    filters = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    if not re.search(r"^\s*\S+\s+ass\s", filters, re.M):
        raise SystemExit(
            "\n\n  Your ffmpeg was built without libass, which ClipForge needs to burn in captions.\n"
            "  Install a full build, then start the app again:\n"
            "    Mac:     brew uninstall ffmpeg && brew install ffmpeg-full\n"
            "             (if `ffmpeg` is then not found, add $(brew --prefix ffmpeg-full)/bin to your PATH)\n"
            "    Windows: winget install Gyan.FFmpeg\n"
            "    Linux:   sudo apt install ffmpeg\n")
    await run_in_threadpool(media.ensure_placeholders)
    jobs = JobManager()
    yield


app = FastAPI(title="ClipForge", lifespan=lifespan)
app.mount("/media/outputs", StaticFiles(directory=config.OUTPUTS_DIR), name="outputs")
app.mount("/media/backgrounds", StaticFiles(directory=config.BACKGROUNDS_DIR), name="backgrounds")
app.mount("/media/music", StaticFiles(directory=config.MUSIC_DIR), name="music")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

CaptionStyle = Literal[tuple(captions.STYLES)]  # type: ignore[valid-type]
DEFAULT_CAPTION = captions.DEFAULT_STYLE  # (models below have a field named `captions`)


# --------------------------------------------------------------------------- request models

class StoryReq(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=20000)
    voice: str = tts.DEFAULT_VOICE
    speed: float = Field(1.0, ge=0.5, le=2.0)
    background: str | None = "random"
    music: str | None = None
    music_volume: float = Field(0.12, ge=0, le=1)
    caption_style: CaptionStyle = DEFAULT_CAPTION
    caption_y: float = Field(0.5, ge=0.1, le=0.9)
    community: str | None = "r/stories"
    author: str | None = "storytime"
    dark_card: bool = False
    part_seconds: int | None = Field(None, ge=20, le=600)


class ChatMessage(BaseModel):
    sender: Literal["me", "them"]
    text: str = Field(max_length=1000)


class ChatReq(BaseModel):
    contact_name: str = Field("Unknown", max_length=40)
    messages: list[ChatMessage] = Field(min_length=1, max_length=120)
    hook: str | None = Field(None, max_length=300)
    voice_me: str = "edge:en-US-BrianMultilingualNeural"
    voice_them: str = "edge:en-US-EmmaMultilingualNeural"
    speed: float = Field(1.1, ge=0.5, le=2.0)
    theme: Literal[tuple(images.CHAT_THEMES)] = "light"  # type: ignore[valid-type]
    background: str | None = "random"
    music: str | None = None
    music_volume: float = Field(0.12, ge=0, le=1)


class SourceReq(BaseModel):
    upload_id: str | None = None
    url: str | None = None

    @model_validator(mode="after")
    def _one_source(self):
        if not (self.upload_id or self.url):
            raise ValueError("Provide upload_id or url")
        return self


class EditReq(SourceReq):
    layout: Literal["split", "blur", "crop"] = "split"
    background: str | None = "random"
    captions: bool = True
    caption_style: CaptionStyle = DEFAULT_CAPTION
    caption_y: float | None = Field(None, ge=0.1, le=0.9)
    start: float | None = Field(None, ge=0)
    end: float | None = Field(None, gt=0)
    max_seconds: float | None = Field(180, gt=0)


class ClipReq(SourceReq):
    count: int = Field(3, ge=1, le=10)
    min_seconds: int = Field(20, ge=5, le=170)
    max_seconds: int = Field(60, ge=10, le=180)
    layout: Literal["split", "blur", "crop"] = "blur"
    background: str | None = "random"
    captions: bool = True
    caption_style: CaptionStyle = DEFAULT_CAPTION
    caption_y: float | None = Field(None, ge=0.1, le=0.9)
    use_ai: bool = True
    language: str | None = None

    @model_validator(mode="after")
    def _range(self):
        if self.max_seconds <= self.min_seconds:
            raise ValueError("max_seconds must be greater than min_seconds")
        return self


class ScriptReq(BaseModel):
    kind: Literal["story", "chat"]
    idea: str = Field(min_length=3, max_length=2000)
    seconds: int = Field(60, ge=15, le=300)


class UrlReq(BaseModel):
    url: str


# --------------------------------------------------------------------------- routes

@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/meta")
def meta():
    return {
        "voices": tts.list_voices(),
        "caption_styles": captions.list_styles(),
        "chat_themes": list(images.CHAT_THEMES),
        "layouts": [{"id": k, "name": v} for k, v in LAYOUTS.items()],
        "backgrounds": media.list_backgrounds(),
        "music": media.list_music(),
        "ai_enabled": config.anthropic_enabled(),
    }


@app.get("/api/backgrounds")
def backgrounds():
    return media.list_backgrounds()


def _save_upload(file: UploadFile, folder) -> dict:
    try:
        path = media.save_upload(file.file, file.filename or "upload.mp4", folder)
    except ValueError as e:
        raise HTTPException(400, str(e))
    public = folder != config.UPLOADS_DIR  # uploaded source videos are not served back
    return {"id": path.name, "name": path.stem, "url": f"/media/{folder.name}/{path.name}" if public else None}


@app.post("/api/backgrounds")
async def upload_background(file: UploadFile = File(...)):
    return await run_in_threadpool(_save_upload, file, config.BACKGROUNDS_DIR)


@app.post("/api/backgrounds/url")
async def background_from_url(req: UrlReq):
    try:
        path = await run_in_threadpool(media.download_url, req.url, config.BACKGROUNDS_DIR)
    except Exception as e:
        raise HTTPException(400, f"Download failed: {e}")
    return {"id": path.name, "name": path.stem, "url": f"/media/backgrounds/{path.name}"}


@app.post("/api/music")
async def upload_music(file: UploadFile = File(...)):
    return await run_in_threadpool(_save_upload, file, config.MUSIC_DIR)


@app.post("/api/uploads")
async def upload_source(file: UploadFile = File(...)):
    return await run_in_threadpool(_save_upload, file, config.UPLOADS_DIR)


@app.post("/api/ai/script")
async def ai_script(req: ScriptReq):
    try:
        if req.kind == "story":
            return await run_in_threadpool(llm.write_story, req.idea, req.seconds)
        return await run_in_threadpool(llm.write_chat, req.idea, max(6, req.seconds // 4))
    except llm.LLMUnavailable as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, str(e))


def _check_assets(background: str | None = None, music: str | None = None, upload_id: str | None = None):
    try:
        if background and background != "random":
            media.background_path(background)
        if music and music != "random":
            media.music_path(music)
        if upload_id:
            media.upload_path(upload_id)
    except FileNotFoundError as e:
        raise HTTPException(400, str(e))


@app.post("/api/jobs/story", status_code=202)
def create_story(req: StoryReq):
    _check_assets(req.background, req.music)
    return jobs.submit("story", req.model_dump(), story.run)


@app.post("/api/jobs/chat", status_code=202)
def create_chat(req: ChatReq):
    _check_assets(req.background, req.music)
    return jobs.submit("chat", req.model_dump(), chat.run)


@app.post("/api/jobs/edit", status_code=202)
def create_edit(req: EditReq):
    _check_assets(req.background if req.layout == "split" else None, upload_id=req.upload_id)
    return jobs.submit("edit", req.model_dump(), edit.run)


@app.post("/api/jobs/clip", status_code=202)
def create_clip(req: ClipReq):
    _check_assets(req.background if req.layout == "split" else None, upload_id=req.upload_id)
    return jobs.submit("clip", req.model_dump(), clipper.run)


@app.get("/api/jobs")
def list_jobs():
    return jobs.list()


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    if not jobs.delete(job_id):
        raise HTTPException(400, "Job not found or still running")
    return {"ok": True}
