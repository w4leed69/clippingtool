"""Shared ffmpeg compositions used by every generator."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .. import config, ffmpeg, media

W, H = config.WIDTH, config.HEIGHT


@dataclass
class Layer:
    """An extra visual input overlaid on the background."""
    input_args: list[str]
    x: str = "(W-w)/2"
    y: str = "(H-h)/2"
    start: float | None = None
    end: float | None = None


def _audio_mix(voice_idx: int | None, music_idx: int | None, music_volume: float) -> tuple[str, str]:
    """Return (filter fragment, output label) for voice + optional music."""
    if voice_idx is not None and music_idx is not None:
        return (f"[{voice_idx}:a]aformat=sample_rates=44100:channel_layouts=stereo[va];"
                f"[{music_idx}:a]aformat=sample_rates=44100:channel_layouts=stereo,volume={music_volume}[ma];"
                f"[va][ma]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]"), "[aout]"
    if music_idx is not None:
        return f"[{music_idx}:a]volume={music_volume}[aout]", "[aout]"
    if voice_idx is not None:
        return f"[{voice_idx}:a]aformat=sample_rates=44100:channel_layouts=stereo[aout]", "[aout]"
    return "", ""


def compose_on_background(*, work: Path, out: Path, bg: Path, duration: float, voice: Path | None,
                          layers: list[Layer], ass: Path | None = None, music: Path | None = None,
                          music_volume: float = 0.12) -> Path:
    args: list[str] = [*media.background_input_args(bg, duration)]
    idx = 1
    voice_idx = music_idx = None
    if voice is not None:
        args += ["-i", str(voice)]
        voice_idx, idx = idx, idx + 1
    if music is not None:
        args += ["-stream_loop", "-1", "-i", str(music)]
        music_idx, idx = idx, idx + 1

    filters = [ffmpeg.cover_filter("0:v", "v0", W, H)]
    cur = "v0"
    for n, layer in enumerate(layers):
        args += layer.input_args
        enable = ""
        if layer.start is not None or layer.end is not None:
            s = layer.start or 0.0
            e = layer.end if layer.end is not None else duration + 1
            enable = f":enable='between(t,{s:.3f},{e:.3f})'"
        filters.append(f"[{cur}][{idx}:v]overlay=x={layer.x}:y={layer.y}{enable}:format=auto[l{n}]")
        cur = f"l{n}"
        idx += 1
    if ass is not None:
        filters.append(f"[{cur}]ass={ass.name}[vcap]")
        cur = "vcap"
    filters.append(f"[{cur}]format=yuv420p[vout]")

    afilter, alabel = _audio_mix(voice_idx, music_idx, music_volume)
    if not alabel:
        args += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
        alabel = f"{idx}:a"
    else:
        filters.append(afilter)

    args += ["-filter_complex", ";".join(filters), "-map", "[vout]", "-map", alabel,
             "-t", f"{duration:.3f}", *ffmpeg.ENCODE_ARGS, str(out)]
    ffmpeg.run(args, cwd=work)
    return out


LAYOUTS = {
    "blur": "Blurred background (keeps full frame)",
    "crop": "Center crop (fills the screen)",
    "split": "Split screen with gameplay below",
}
DEFAULT_CAPTION_Y = {"blur": 0.72, "crop": 0.7, "split": 0.5}


def render_vertical(*, work: Path, out: Path, src: Path, start: float, end: float, layout: str = "blur",
                    ass: Path | None = None, bg: Path | None = None, top_ratio: float = 0.5) -> Path:
    """Cut ``src`` from start..end and reframe it to 1080x1920 using ``layout``."""
    length = max(end - start, 0.5)
    args: list[str] = ["-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(src)]
    if layout == "split":
        if bg is None:
            raise ValueError("Split layout needs a background video")
        top_h = int(H * top_ratio) // 2 * 2
        args += media.background_input_args(bg, length)
        filters = [ffmpeg.cover_filter("0:v", "top", W, top_h),
                   ffmpeg.cover_filter("1:v", "bottom", W, H - top_h),
                   "[top][bottom]vstack=inputs=2[v0]"]
    elif layout == "crop":
        filters = [ffmpeg.cover_filter("0:v", "v0", W, H)]
    elif layout == "blur":
        filters = ["[0:v]split=2[a][b]",
                   f"[a]scale={W // 4}:{H // 4}:force_original_aspect_ratio=increase,crop={W // 4}:{H // 4},"
                   f"gblur=sigma=12,eq=brightness=-0.12,scale={W}:{H},setsar=1[bgv]",
                   f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease,setsar=1[fg]",
                   "[bgv][fg]overlay=(W-w)/2:(H-h)/2[v0]"]
    else:
        raise ValueError(f"Unknown layout '{layout}'")
    cur = "v0"
    if ass is not None:
        filters.append(f"[{cur}]ass={ass.name}[vcap]")
        cur = "vcap"
    filters.append(f"[{cur}]format=yuv420p[vout]")
    if ffmpeg.has_audio(src):
        amap = "0:a:0"
    else:
        args += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
        amap = f"{2 if layout == 'split' else 1}:a"
    args += ["-filter_complex", ";".join(filters), "-map", "[vout]", "-map", amap,
             "-t", f"{length:.3f}", *ffmpeg.ENCODE_ARGS, str(out)]
    ffmpeg.run(args, cwd=work)
    return out
