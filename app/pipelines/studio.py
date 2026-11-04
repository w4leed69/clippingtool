"""AI Studio: one video in, polished shorts out.

Steps (each optional): AI clipping -> AI reframe -> AI audio enhance -> AI voice-over -> AI B-roll ->
AI captions. Every clip is processed independently so they can be posted as separate shorts.
"""
from __future__ import annotations

import base64
import re
from pathlib import Path

from .. import captions, config, ffmpeg, llm, media, transcribe, tts
from ..ai import audio, broll, highlights, reframe
from ..jobs import JobContext

ASPECTS = {"9:16": (1080, 1920), "1:1": (1080, 1080), "16:9": (1920, 1080)}
CAPTION_Y = {"ai": 0.72, "center": 0.72, "blur": 0.75, "split": 0.5, "none": 0.82}
MAX_UNCLIPPED = 15 * 60


def cut_segment(src: Path, start: float, end: float, out: Path) -> Path:
    """Exact cut at constant 30 fps, capped at 1080p, so later steps can count frames."""
    ffmpeg.run(["-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", src,
                "-vf", "fps=30,scale=-2:'min(1080,ih)'", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", out])
    return out


def video_size(path: Path) -> tuple[int, int]:
    v = next(s for s in ffmpeg.probe(path)["streams"] if s["codec_type"] == "video")
    return int(v["width"]), int(v["height"])


def filter_reframe(seg: Path, out: Path, mode: str, w: int, h: int, bg: Path | None) -> Path:
    """Non-AI reframes done with ffmpeg filters (video only)."""
    dur = ffmpeg.duration(seg)
    args: list[str] = ["-i", str(seg)]
    if mode == "center":
        graph = ffmpeg.cover_filter("0:v", "v", w, h)
    elif mode == "blur":
        graph = (f"[0:v]split=2[a][b];[a]scale={w // 4}:{h // 4}:force_original_aspect_ratio=increase,"
                 f"crop={w // 4}:{h // 4},gblur=sigma=12,eq=brightness=-0.12,scale={w}:{h},setsar=1[bg];"
                 f"[b]scale={w}:{h}:force_original_aspect_ratio=decrease,setsar=1[fg];"
                 "[bg][fg]overlay=(W-w)/2:(H-h)/2[v]")
    elif mode == "split":
        top = h // 2 // 2 * 2
        args += media.background_input_args(bg, dur)
        graph = (ffmpeg.cover_filter("0:v", "t", w, top) + ";" + ffmpeg.cover_filter("1:v", "b", w, h - top)
                 + ";[t][b]vstack=inputs=2[v]")
    else:
        raise ValueError(f"Unknown reframe mode '{mode}'")
    ffmpeg.run([*args, "-filter_complex", graph, "-map", "[v]", "-an", "-t", f"{dur:.3f}", "-c:v", "libx264",
                "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-r", "30", out])
    return out


def sample_frames(seg: Path, work: Path, n: int = 6) -> list[str]:
    dur = ffmpeg.duration(seg)
    frames = []
    for k in range(n):
        f = work / f"frame{k}.jpg"
        ffmpeg.run(["-ss", f"{dur * (k + 0.5) / n:.2f}", "-i", seg, "-frames:v", "1", "-vf", "scale=512:-2", f])
        frames.append(base64.b64encode(f.read_bytes()).decode())
    return frames


def fallback_emphasis(words: list[tts.Word]) -> set[str]:
    out = set()
    for w in words:
        n = captions.norm_word(w.text)
        if re.search(r"\d", n) or n in highlights.HYPE_WORDS:
            out.add(n)
    return out


def compose(*, work: Path, out: Path, video: Path, audio_wav: Path, duration: float, w: int, h: int,
            brolls: list[dict], ass: Path | None) -> Path:
    args = ["-i", str(video), "-i", str(audio_wav)]
    graph, cur = [], "0:v"
    for k, b in enumerate(brolls):
        idx = k + 2
        args += ["-stream_loop", "-1", "-i", str(b["path"])]
        length = b["end"] - b["start"]
        graph.append(f"[{idx}:v]trim=duration={length:.3f},setpts=PTS-STARTPTS+{b['start']:.3f}/TB,"
                     f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,"
                     f"fade=t=in:st={b['start']:.3f}:d=0.15[b{k}]")
        graph.append(f"[{cur}][b{k}]overlay=eof_action=pass:enable='between(t,{b['start']:.3f},{b['end']:.3f})'[o{k}]")
        cur = f"o{k}"
    if ass is not None:
        graph.append(f"[{cur}]ass={ass.name}[c]")
        cur = "c"
    graph.append(f"[{cur}]format=yuv420p[vout]")
    ffmpeg.run([*args, "-filter_complex", ";".join(graph), "-map", "[vout]", "-map", "1:a",
                "-t", f"{duration:.3f}", *ffmpeg.ENCODE_ARGS, str(out)], cwd=work)
    return out


def run(ctx: JobContext, p: dict) -> None:
    ai = p.get("use_ai", True) and config.anthropic_enabled()
    notes: list[str] = []

    ctx.update(0.02, "Fetching video")
    src = media.resolve_source(p.get("upload_id"), p.get("url"), ctx.work)
    total = ffmpeg.duration(src)
    has_speech_track = ffmpeg.has_audio(src)
    vo_on = p.get("voiceover", False)
    if vo_on and not (p.get("vo_script") or "").strip() and not ai:
        raise ValueError("Write a voice-over script, or set ANTHROPIC_API_KEY so AI can write one")
    needs_transcript = has_speech_track and (p.get("clip") or p.get("captions") or p.get("broll")
                                             or (vo_on and not p.get("vo_script")))

    segments: list[transcribe.Segment] = []
    if needs_transcript:
        ctx.update(0.05, "Transcribing speech (longer videos take a few minutes)")
        wav = ctx.work / "speech.wav"
        ffmpeg.run(["-i", src, "-vn", "-ac", "1", "-ar", "16000", wav])
        segments = transcribe.transcribe(wav, language=p.get("language"))

    # ---- AI clipping: which ranges to turn into shorts
    if p.get("clip"):
        if not segments:
            raise ValueError("AI clipping needs speech in the video to find the best moments")
        ctx.update(0.25, "Finding the best moments")
        ranges, picker, note = highlights.pick(segments, total, p.get("clip_count", 3), p.get("clip_min", 20),
                                               p.get("clip_max", 60), use_ai=ai)
        if note:
            notes.append(note)
        if not ranges:
            raise ValueError("No clip fits the length range you chose; try a wider range")
    else:
        start = max(0.0, p.get("start") or 0.0)
        end = min(total, p.get("end") or total)
        if end - start > MAX_UNCLIPPED:
            end = start + MAX_UNCLIPPED
            notes.append("Video was longer than 15 minutes; only the first 15 were processed")
        ranges, picker = [{"start": start, "end": end, "title": src.stem}], None

    mode = p.get("reframe", "ai")
    w, h = ASPECTS.get(p.get("aspect", "9:16"), ASPECTS["9:16"])
    bg = media.background_path(p.get("background")) if mode == "split" else None

    for i, r in enumerate(ranges):
        base, span = 0.3 + 0.7 * i / len(ranges), 0.7 / len(ranges)
        tag = f"clip {i + 1}/{len(ranges)}"
        work = ctx.work / f"c{i}"
        work.mkdir()
        applied, clip_notes = [], []

        def step(frac: float, msg: str) -> None:
            ctx.update(base + span * frac, f"{msg} ({tag})")

        step(0.0, "Cutting")
        seg = cut_segment(src, r["start"], r["end"], work / "seg.mp4")
        dur = ffmpeg.duration(seg)
        words = transcribe.words_between(segments, r["start"], r["end"]) if segments else []

        # ---- AI reframe
        video = work / "video.mp4"
        out_w, out_h = w, h
        if mode == "none":
            out_w, out_h = (v // 2 * 2 for v in video_size(seg))
            ffmpeg.run(["-i", seg, "-an", "-vf", f"scale={out_w}:{out_h}", "-c:v", "libx264", "-preset", "veryfast",
                        "-crf", "18", "-pix_fmt", "yuv420p", video])
        elif mode == "ai":
            step(0.05, "AI reframe: tracking faces")
            stats = reframe.reframe(seg, video, w, h, progress=lambda f: step(0.05 + 0.35 * f, "AI reframe"))
            if stats["face_coverage"] < 0.15:
                filter_reframe(seg, video, "blur", w, h, None)
                clip_notes.append("No face found, so the full frame was kept with a blurred fill")
            else:
                applied.append("AI reframe")
        else:
            step(0.1, "Reframing")
            filter_reframe(seg, video, mode, w, h, bg)

        # ---- AI audio enhance
        step(0.45, "Processing audio")
        track = audio.extract(seg, work / "orig.wav")
        if p.get("enhance") and has_speech_track:
            track = audio.enhance(track, work / "enhanced.wav", p.get("enhance_level", "studio"))
            applied.append("Audio enhance")

        # ---- AI voice-over
        caption_words = words
        script = None
        if vo_on:
            step(0.5, "Writing voice-over")
            script = (p.get("vo_script") or "").strip()
            if not script:
                if not ai:
                    raise ValueError("Write a voice-over script, or set ANTHROPIC_API_KEY so AI can write one")
                script = llm.write_voiceover(sample_frames(seg, work), dur,
                                             " ".join(x.text for x in words), p.get("vo_instructions") or "")
            step(0.55, "Recording voice-over")
            voice, speed = p.get("vo_voice") or tts.DEFAULT_VOICE, p.get("vo_speed", 1.0)
            speech = tts.synthesize(script, voice, work, "vo", speed)
            if speech.duration > dur * 1.03:  # speed up to fit, within reason
                speed = min(speed * speech.duration / dur, 1.5)
                speech = tts.synthesize(script, voice, work, "vo", speed)
                if speech.duration > dur * 1.03:
                    clip_notes.append("Voice-over was longer than the clip and was cut off at the end")
            mixed = audio.mix_voiceover(track, speech.audio, work / "mixed.wav", p.get("vo_mode", "duck"), dur)
            track = mixed
            caption_words = [x for x in speech.words if x.start < dur]
            applied.append("AI voice-over")

        # ---- AI B-roll
        brolls: list[dict] = []
        if p.get("broll"):
            step(0.6, "Finding B-roll")
            spoken = caption_words if caption_words and caption_words[-1].end >= 6 else words
            moments = broll.plan(spoken, p.get("broll_count", 3), use_ai=ai)
            brolls = broll.fetch(moments, work, portrait=out_h > out_w)
            if brolls:
                applied.append(f"B-roll x{len(brolls)}")
            elif moments:
                clip_notes.append("No B-roll footage found; add PEXELS_API_KEY or put clips in data/broll/")

        # ---- AI captions
        ass = srt = None
        if p.get("captions") and caption_words:
            step(0.7, "Styling captions")
            emphasis: set[str] = set()
            if p.get("caption_emphasis", True):
                try:
                    emphasis = ({captions.norm_word(x) for x in llm.pick_emphasis(" ".join(c.text for c in caption_words))}
                                if ai else fallback_emphasis(caption_words))
                except Exception:
                    emphasis = fallback_emphasis(caption_words)
            y = p.get("caption_y") or CAPTION_Y.get(mode, 0.72)
            ass = captions.build_ass(caption_words, work / "subs.ass", p.get("caption_style", captions.DEFAULT_STYLE),
                                     y=y, width=out_w, height=out_h, emphasis=emphasis)
            applied.append("AI captions")
        elif p.get("captions"):
            clip_notes.append("No speech found to caption")

        step(0.75, "Rendering")
        out = ctx.output_path()
        compose(work=work, out=out, video=video, audio_wav=track, duration=dur, w=out_w, h=out_h,
                brolls=brolls, ass=ass)
        if ass is not None:
            srt = captions.build_srt(caption_words, out.with_suffix(".srt"))
        ctx.add_output(out, title=r.get("title") or f"Clip {i + 1}", hook=r.get("hook", ""), score=r.get("score"),
                       start=r["start"], end=r["end"], picker=picker, features=applied,
                       notes=notes + clip_notes, script=script,
                       srt=f"/media/outputs/{srt.name}" if srt else None,
                       broll=[{"query": b["query"], "start": b["start"]} for b in brolls])
