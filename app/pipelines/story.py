"""Narrated story videos: title card + voiceover + animated captions over background gameplay."""
from __future__ import annotations

import re

from .. import captions, ffmpeg, media, tts
from ..jobs import JobContext
from ..render import images
from .compose import Layer, compose_on_background

TITLE_GAP = 0.35
WORDS_PER_SECOND = 2.6


def split_parts(body: str, part_seconds: int | None) -> list[str]:
    """Split a long story on sentence boundaries into parts of roughly ``part_seconds`` of narration."""
    body = body.strip()
    if not part_seconds:
        return [body]
    budget = part_seconds * WORDS_PER_SECOND
    sentences = re.split(r"(?<=[.!?])\s+", body)
    parts, cur, count = [], [], 0
    for s in sentences:
        n = len(s.split())
        if cur and count + n > budget:
            parts.append(" ".join(cur))
            cur, count = [], 0
        cur.append(s)
        count += n
    if cur:
        parts.append(" ".join(cur))
    # fold a tiny trailing part into the previous one
    if len(parts) > 1 and len(parts[-1].split()) < budget * 0.25:
        tail = parts.pop()
        parts[-1] = f"{parts[-1]} {tail}"
    return parts


def run(ctx: JobContext, p: dict) -> None:
    parts = split_parts(p["body"], p.get("part_seconds"))
    bg = media.background_path(p.get("background"))
    music = media.music_path(p.get("music"))
    for i, body in enumerate(parts, start=1):
        base = (i - 1) / len(parts)
        span = 1 / len(parts)
        label = f"part {i}/{len(parts)}" if len(parts) > 1 else "video"
        work = ctx.work / f"part{i}"
        work.mkdir(exist_ok=True)

        title = p["title"] if len(parts) == 1 else f"{p['title']} (Part {i})"
        ctx.update(base + span * 0.05, f"Generating voiceover ({label})")
        t_speech = tts.synthesize(title, p["voice"], work, "title", p.get("speed", 1.0))
        b_speech = tts.synthesize(body, p["voice"], work, "body", p.get("speed", 1.0))
        gap = ffmpeg.silence(work / "gap.wav", TITLE_GAP)
        voice = ffmpeg.concat_wavs([t_speech.audio, gap, b_speech.audio], work / "voice.wav")
        offset = t_speech.duration + TITLE_GAP
        words = [w.shifted(offset) for w in b_speech.words]
        duration = ffmpeg.duration(voice) + 0.8

        ctx.update(base + span * 0.3, f"Drawing title card ({label})")
        card = images.story_card(title, work / "card.png", author=p.get("author") or "storytime",
                                 community=p.get("community") or "r/stories", dark=p.get("dark_card", False))
        ass = captions.build_ass(words, work / "subs.ass", p.get("caption_style", captions.DEFAULT_STYLE),
                                 y=p.get("caption_y", 0.5))

        ctx.update(base + span * 0.4, f"Rendering ({label})")
        out = ctx.output_path()
        compose_on_background(
            work=work, out=out, bg=bg, duration=duration, voice=voice,
            layers=[Layer(["-loop", "1", "-i", str(card)], start=0, end=t_speech.duration + 0.15)],
            ass=ass, music=music, music_volume=p.get("music_volume", 0.12),
        )
        ctx.add_output(out, title=title)
