"""Text-conversation story videos: chat bubbles appear one by one, each read aloud by its own voice."""
from __future__ import annotations

from PIL import Image

from .. import ffmpeg, media, tts
from ..jobs import JobContext
from ..render import images
from .compose import Layer, compose_on_background

GAP = 0.25          # pause between messages
CANVAS_W, CANVAS_H = 940, 1250


def run(ctx: JobContext, p: dict) -> None:
    msgs = [m for m in p["messages"] if m["text"].strip()]
    if not msgs:
        raise ValueError("Add at least one message")
    work = ctx.work
    bg = media.background_path(p.get("background"))
    music = media.music_path(p.get("music"))
    speed = p.get("speed", 1.0)

    audio_parts, durations = [], []
    hook_dur = 0.0
    if p.get("hook"):
        ctx.update(0.03, "Voicing the hook")
        hook = tts.synthesize(p["hook"], p.get("voice_them") or tts.DEFAULT_VOICE, work, "hook", speed)
        audio_parts += [hook.audio, ffmpeg.silence(work / "hookgap.wav", 0.3)]
        hook_dur = hook.duration + 0.3

    gap = ffmpeg.silence(work / "gap.wav", GAP)
    for i, m in enumerate(msgs):
        ctx.update(0.05 + 0.45 * i / len(msgs), f"Voicing message {i + 1}/{len(msgs)}")
        voice = p["voice_me"] if m["sender"] == "me" else p["voice_them"]
        speech = tts.synthesize(m["text"], voice, work, f"m{i}", speed)
        audio_parts += [speech.audio, gap]
        durations.append(speech.duration + GAP)
    voice_track = ffmpeg.concat_wavs(audio_parts, work / "voice.wav")

    ctx.update(0.55, "Drawing chat screens")
    contact = p.get("contact_name") or "Unknown"
    theme = p.get("theme", "light")

    def frame(shown: list[dict], name: str) -> str:
        raw = images.chat_frame(shown, contact, work / f"raw-{name}.png", theme=theme,
                                width=CANVAS_W, max_height=CANVAS_H)
        canvas = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
        canvas.paste(Image.open(raw), (0, 0))
        canvas.save(work / f"{name}.png")
        return f"{name}.png"

    concat_lines = []
    if hook_dur:
        concat_lines += [f"file '{frame([], 'frame-hook')}'", f"duration {hook_dur:.3f}"]
    last = ""
    for i in range(len(msgs)):
        last = frame(msgs[: i + 1], f"frame{i:03d}")
        concat_lines += [f"file '{last}'", f"duration {durations[i]:.3f}"]
    concat_lines.append(f"file '{last}'")  # the concat demuxer needs the last file listed twice
    (work / "frames.txt").write_text("\n".join(concat_lines) + "\n")

    total = ffmpeg.duration(voice_track) + 0.8
    ctx.update(0.65, "Rendering video")
    out = ctx.output_path()
    compose_on_background(
        work=work, out=out, bg=bg, duration=total, voice=voice_track,
        layers=[Layer(["-f", "concat", "-safe", "0", "-i", "frames.txt"], y="140")],
        music=music, music_volume=p.get("music_volume", 0.12),
    )
    ctx.add_output(out, title=p.get("contact_name") or "Text story")
