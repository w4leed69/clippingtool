"""AI audio enhance and voice-over mixing (ffmpeg DSP chains)."""
from __future__ import annotations

from pathlib import Path

from .. import ffmpeg

# Speech-focused cleanup: cut rumble and hiss, adaptive noise reduction, tame harsh "s" sounds,
# even out levels, then normalize to the -14 LUFS loudness that TikTok/Reels/Shorts use.
ENHANCE_LEVELS = {
    "light": "highpass=f=70,afftdn=nr=8:nf=-35:tn=1,acompressor=threshold=-20dB:ratio=2:attack=10:release=150,"
             "loudnorm=I=-14:TP=-1.5:LRA=11",
    "studio": "highpass=f=80,lowpass=f=15000,afftdn=nr=14:nf=-30:tn=1,deesser=i=0.4,"
              "equalizer=f=200:t=q:w=1:g=-2,equalizer=f=3500:t=q:w=1.2:g=3,"
              "acompressor=threshold=-18dB:ratio=3:attack=5:release=120:makeup=2,"
              "loudnorm=I=-14:TP=-1.5:LRA=9",
}


def extract(src: Path, out: Path) -> Path:
    """Source audio as 44.1k stereo wav, or silence of the same length if the video has none."""
    if ffmpeg.has_audio(src):
        ffmpeg.run(["-i", src, "-vn", "-ac", "2", "-ar", "44100", out])
    else:
        ffmpeg.run(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", f"{ffmpeg.duration(src):.3f}", out])
    return out


def enhance(src_wav: Path, out: Path, level: str = "studio") -> Path:
    ffmpeg.run(["-i", src_wav, "-af", ENHANCE_LEVELS.get(level, ENHANCE_LEVELS["studio"]), "-ar", "44100", out])
    return out


def mix_voiceover(original: Path, voice: Path, out: Path, mode: str, duration: float,
                  original_volume: float = 0.25) -> Path:
    """Put a voice-over on top of the original audio.

    ``duck``: original keeps playing but automatically drops whenever the voice speaks.
    ``replace``: voice only.
    """
    if mode == "replace":
        ffmpeg.run(["-i", voice, "-af", f"aformat=channel_layouts=stereo,apad,atrim=0:{duration:.3f},"
                    "loudnorm=I=-14:TP=-1.5", "-ar", "44100", out])
        return out
    graph = (
        f"[1:a]aformat=sample_rates=44100:channel_layouts=stereo,apad,atrim=0:{duration:.3f},asplit=2[vo][key];"
        f"[0:a]aformat=sample_rates=44100:channel_layouts=stereo,volume={original_volume * 2:.2f}[bed];"
        "[bed][key]sidechaincompress=threshold=0.02:ratio=8:attack=20:release=400[ducked];"
        "[ducked][vo]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5[a]"
    )
    ffmpeg.run(["-i", original, "-i", voice, "-filter_complex", graph, "-map", "[a]", "-ar", "44100",
                "-t", f"{duration:.3f}", out])
    return out
