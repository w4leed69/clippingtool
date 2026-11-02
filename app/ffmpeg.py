"""Thin helpers around the ffmpeg / ffprobe command line tools."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from . import config

ENCODE_ARGS = [
    "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
    "-r", str(config.FPS), "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
    "-movflags", "+faststart",
]


class FFmpegError(RuntimeError):
    pass


def run(args: list[str], cwd: Path | None = None) -> None:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *map(str, args)]
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise FFmpegError(f"ffmpeg failed: {proc.stderr.strip()[-2000:]}")


def probe(path: Path) -> dict:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise FFmpegError(f"ffprobe failed on {path}: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def duration(path: Path) -> float:
    info = probe(path)
    d = info.get("format", {}).get("duration")
    if d is None:
        for s in info.get("streams", []):
            if s.get("duration"):
                d = s["duration"]
                break
    return float(d or 0.0)


def has_audio(path: Path) -> bool:
    return any(s.get("codec_type") == "audio" for s in probe(path).get("streams", []))


def to_wav(src: Path, dst: Path) -> Path:
    run(["-i", src, "-ac", "1", "-ar", "44100", dst])
    return dst


def silence(dst: Path, seconds: float) -> Path:
    run(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", f"{seconds:.3f}", dst])
    return dst


def concat_wavs(parts: list[Path], dst: Path) -> Path:
    """Concatenate mono 44.1k wav files (as produced by to_wav / silence)."""
    inputs: list[str] = []
    for p in parts:
        inputs += ["-i", str(p)]
    labels = "".join(f"[{i}:a]" for i in range(len(parts)))
    run([*inputs, "-filter_complex", f"{labels}concat=n={len(parts)}:v=0:a=1[a]", "-map", "[a]", dst])
    return dst


def cover_filter(label_in: str, label_out: str, w: int, h: int) -> str:
    """Scale + center-crop a stream so it completely fills w x h."""
    return (
        f"[{label_in}]scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h},setsar=1[{label_out}]"
    )


def fit_filter(label_in: str, label_out: str, w: int, h: int) -> str:
    """Scale a stream so it fits inside w x h without cropping."""
    return f"[{label_in}]scale={w}:{h}:force_original_aspect_ratio=decrease,setsar=1[{label_out}]"
