"""AI clipper: turn a long video into several captioned vertical shorts."""
from __future__ import annotations

import re

from .. import captions, config, ffmpeg, llm, media, transcribe
from ..jobs import JobContext
from .compose import DEFAULT_CAPTION_Y, render_vertical

HYPE_WORDS = {
    "insane", "crazy", "never", "secret", "biggest", "worst", "best", "actually", "literally", "wait",
    "unbelievable", "shocking", "truth", "mistake", "million", "money", "love", "hate", "why", "how",
    "nobody", "everyone", "first", "last", "stop", "wow", "omg", "funny", "story", "honestly",
}


def format_transcript(segments: list[transcribe.Segment]) -> str:
    return "\n".join(f"[{s.start:.1f}-{s.end:.1f}] {s.text}" for s in segments)


def heuristic_highlights(segments: list[transcribe.Segment], count: int, min_len: float,
                         max_len: float) -> list[dict]:
    """Score windows that start/end on segment boundaries; pick the best non-overlapping ones."""
    target = (min_len + max_len) / 2
    candidates = []
    for i, first in enumerate(segments):
        best_end, text = None, []
        for seg in segments[i:]:
            length = seg.end - first.start
            if length > max_len:
                break
            text.append(seg.text)
            if length >= min_len and (best_end is None or abs(length - target) < abs(best_end - first.start - target)):
                best_end = seg.end
                best_text = " ".join(text)
        if best_end is None:
            continue
        words = re.findall(r"[a-zA-Z']+", best_text.lower())
        dur = best_end - first.start
        wps = len(words) / dur
        hype = sum(w in HYPE_WORDS for w in words)
        punct = best_text.count("!") * 2 + best_text.count("?")
        hook = sum(w in HYPE_WORDS for w in re.findall(r"[a-zA-Z']+", first.text.lower())) * 3
        score = wps * 10 + hype * 2 + punct + hook
        candidates.append({"start": first.start, "end": best_end, "score": score,
                           "title": _title_from(first.text), "hook": first.text})
    candidates.sort(key=lambda c: c["score"], reverse=True)
    chosen: list[dict] = []
    for c in candidates:
        if all(c["end"] <= o["start"] or c["start"] >= o["end"] for o in chosen):
            chosen.append(c)
        if len(chosen) >= count:
            break
    top = max((c["score"] for c in chosen), default=1) or 1
    for c in chosen:
        c["score"] = int(40 + 55 * c["score"] / top)
    return sorted(chosen, key=lambda c: c["start"])


def _title_from(text: str) -> str:
    words = text.split()
    return " ".join(words[:8]) + ("…" if len(words) > 8 else "")


def sanitize(clips: list[dict], total: float, min_len: float, max_len: float) -> list[dict]:
    out = []
    for c in clips:
        s, e = max(0.0, float(c["start"])), min(total, float(c["end"]))
        if e - s > max_len * 1.25:
            e = s + max_len
        if e - s < min(min_len, 5):
            continue
        if any(not (e <= o["start"] or s >= o["end"]) for o in out):
            continue
        out.append({**c, "start": round(s, 2), "end": round(e, 2)})
    return out


def run(ctx: JobContext, p: dict) -> None:
    ctx.update(0.02, "Fetching source video")
    src = media.resolve_source(p.get("upload_id"), p.get("url"), ctx.work)
    total = ffmpeg.duration(src)
    min_len, max_len = p.get("min_seconds", 20), p.get("max_seconds", 60)
    count = p.get("count", 3)

    ctx.update(0.08, "Transcribing (this takes a while for long videos)")
    audio = ctx.work / "audio.wav"
    ffmpeg.run(["-i", src, "-vn", "-ac", "1", "-ar", "16000", audio])
    segments = transcribe.transcribe(audio, language=p.get("language"))
    if not segments:
        raise ValueError("No speech found in this video")

    ctx.update(0.4, "Finding the best moments")
    clips = None
    picker = "heuristic"
    if p.get("use_ai", True) and config.anthropic_enabled():
        try:
            clips = llm.pick_highlights(format_transcript(segments), count, min_len, max_len)
            picker = "claude"
        except Exception as e:  # fall back to the local scorer on any AI failure
            ctx.update(message=f"AI picker unavailable ({e}); using built-in scorer")
    if not clips:
        clips = heuristic_highlights(segments, count, min_len, max_len)
    clips = sanitize(clips, total, min_len, max_len)[:count]
    if not clips:
        raise ValueError("Could not find any clip in the requested length range; try a wider range")

    layout = p.get("layout", "blur")
    bg = media.background_path(p.get("background")) if layout == "split" else None
    for i, c in enumerate(clips):
        ctx.update(0.45 + 0.55 * i / len(clips), f"Rendering clip {i + 1}/{len(clips)}")
        ass = None
        if p.get("captions", True):
            words = transcribe.words_between(segments, c["start"], c["end"])
            ass = captions.build_ass(words, ctx.work / f"subs{i}.ass", p.get("caption_style", captions.DEFAULT_STYLE),
                                     y=p.get("caption_y") or DEFAULT_CAPTION_Y[layout])
        out = ctx.output_path()
        render_vertical(work=ctx.work, out=out, src=src, start=c["start"], end=c["end"], layout=layout, ass=ass, bg=bg)
        ctx.add_output(out, title=c.get("title", f"Clip {i + 1}"), hook=c.get("hook", ""),
                       score=c.get("score"), start=c["start"], end=c["end"], picker=picker)
