"""Reframe an existing video to vertical: split-screen with gameplay, or blurred background."""
from __future__ import annotations

from .. import captions, ffmpeg, media, transcribe
from ..jobs import JobContext
from .compose import DEFAULT_CAPTION_Y, render_vertical


def run(ctx: JobContext, p: dict) -> None:
    layout = p["layout"]
    ctx.update(0.03, "Fetching source video")
    src = media.resolve_source(p.get("upload_id"), p.get("url"), ctx.work)
    total = ffmpeg.duration(src)
    start = max(0.0, p.get("start") or 0.0)
    end = min(total, p["end"]) if p.get("end") else total
    if p.get("max_seconds"):
        end = min(end, start + p["max_seconds"])
    if end - start < 0.5:
        raise ValueError("The selected range is too short")

    ass = None
    if p.get("captions", True):
        ctx.update(0.15, "Transcribing speech for captions")
        audio = ctx.work / "audio.wav"
        if not ffmpeg.has_audio(src):
            raise ValueError("This video has no audio to caption; turn captions off")
        ffmpeg.run(["-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", src, "-vn", "-ac", "1",
                    "-ar", "16000", audio])
        segs = transcribe.transcribe(audio)
        words = [w for s in segs for w in s.words]  # already relative to `start`
        if words:
            y = p.get("caption_y") or DEFAULT_CAPTION_Y[layout]
            ass = captions.build_ass(words, ctx.work / "subs.ass", p.get("caption_style", captions.DEFAULT_STYLE), y=y)

    ctx.update(0.45, "Rendering")
    bg = media.background_path(p.get("background")) if layout == "split" else None
    out = ctx.output_path()
    render_vertical(work=ctx.work, out=out, src=src, start=start, end=end, layout=layout, ass=ass, bg=bg)
    ctx.add_output(out, title=src.stem)
