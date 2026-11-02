"""Background library, music library, uploads and URL downloads."""
from __future__ import annotations

import random
import re
import shutil
import uuid
from pathlib import Path

from . import config, ffmpeg

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}

# Procedural placeholder backgrounds so the app works before you add your own gameplay footage.
PLACEHOLDERS = {
    "placeholder-neon-gradient": "gradients=s=540x960:r=30:speed=0.015:n=4:c0=0x7b2ff7:c1=0xf107a3:c2=0x00d4ff:c3=0x1b1464",
    "placeholder-sunset-gradient": "gradients=s=540x960:r=30:speed=0.02:n=3:c0=0xff7e5f:c1=0xfeb47b:c2=0x6a3093:type=radial",
    "placeholder-game-of-life": "life=s=540x960:r=30:mold=10:ratio=0.1:death_color=#1a1033:life_color=#39ff14,scale=540:960",
}


def safe_name(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(name).stem).strip("-")[:60] or "file"
    return stem


def ensure_placeholders() -> None:
    for name, src in PLACEHOLDERS.items():
        out = config.BACKGROUNDS_DIR / f"{name}.mp4"
        if out.exists():
            continue
        tmp = out.with_suffix(".tmp.mp4")
        ffmpeg.run(["-f", "lavfi", "-i", src, "-t", "20", "-an", "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", "26", "-pix_fmt", "yuv420p", tmp])
        tmp.rename(out)


def _library(folder: Path, exts: set[str]) -> list[dict]:
    items = []
    for p in sorted(folder.iterdir()):
        if p.suffix.lower() in exts and not p.name.endswith(".tmp.mp4"):
            items.append({"id": p.name, "name": p.stem.replace("-", " ").replace("_", " ").title(),
                          "url": f"/media/{folder.name}/{p.name}"})
    return items


def list_backgrounds() -> list[dict]:
    return _library(config.BACKGROUNDS_DIR, VIDEO_EXTS)


def list_music() -> list[dict]:
    return _library(config.MUSIC_DIR, AUDIO_EXTS)


def _in_folder(folder: Path, name: str) -> Path:
    p = (folder / Path(name).name).resolve()
    if p.parent != folder.resolve() or not p.exists():
        raise FileNotFoundError(f"'{name}' not found")
    return p


def background_path(name: str | None) -> Path:
    if not name or name == "random":
        items = list_backgrounds()
        real = [i for i in items if not i["id"].startswith("placeholder-")]
        pick = random.choice(real or items)
        return config.BACKGROUNDS_DIR / pick["id"]
    return _in_folder(config.BACKGROUNDS_DIR, name)


def music_path(name: str | None) -> Path | None:
    if not name:
        return None
    if name == "random":
        items = list_music()
        return config.MUSIC_DIR / random.choice(items)["id"] if items else None
    return _in_folder(config.MUSIC_DIR, name)


def upload_path(file_id: str) -> Path:
    return _in_folder(config.UPLOADS_DIR, file_id)


def save_upload(fileobj, filename: str, folder: Path) -> Path:
    ext = Path(filename).suffix.lower()
    if ext not in VIDEO_EXTS | AUDIO_EXTS:
        raise ValueError(f"Unsupported file type '{ext}'")
    dest = folder / f"{safe_name(filename)}-{uuid.uuid4().hex[:6]}{ext}"
    with open(dest, "wb") as f:
        shutil.copyfileobj(fileobj, f)
    return dest


def download_url(url: str, folder: Path, max_height: int = 1080) -> Path:
    """Download a video with yt-dlp. Only use this on content you have the rights to reuse."""
    try:
        import yt_dlp
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("yt-dlp is not installed") from e
    token = uuid.uuid4().hex[:6]
    opts = {
        "format": f"bv*[height<={max_height}][ext=mp4]+ba[ext=m4a]/b[height<={max_height}]/b",
        "merge_output_format": "mp4",
        "outtmpl": str(folder / f"%(title).50B-{token}.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = Path(ydl.prepare_filename(info))
    if not path.exists():
        candidates = sorted(folder.glob(f"*-{token}.*"))
        if not candidates:
            raise RuntimeError("Download finished but the file was not found")
        path = candidates[0]
    if path.suffix.lower() != ".mp4":
        mp4 = path.with_suffix(".mp4")
        ffmpeg.run(["-i", path, "-c", "copy", mp4])
        path.unlink(missing_ok=True)
        path = mp4
    return path


def resolve_source(upload_id: str | None, url: str | None, work: Path) -> Path:
    if upload_id:
        return upload_path(upload_id)
    if url:
        return download_url(url, config.UPLOADS_DIR)
    raise ValueError("Provide either an uploaded file or a video URL")


def background_input_args(bg: Path, needed: float) -> list[str]:
    """ffmpeg input args that start at a random point of the background and loop it if it's short."""
    bg_dur = ffmpeg.duration(bg)
    start = random.uniform(0, bg_dur - needed) if bg_dur > needed + 1 else 0.0
    return ["-ss", f"{start:.2f}", "-stream_loop", "-1", "-i", str(bg)]
