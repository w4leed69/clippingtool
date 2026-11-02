"""Text-to-speech with word-level timings.

Voice ids are namespaced by provider:

* ``edge:<VoiceName>``    free Microsoft Edge neural voices (default, needs internet)
* ``eleven:<voice_id>``   ElevenLabs (needs ELEVENLABS_API_KEY)
* ``silent``              no audio, estimated timings; handy for previews and tests
"""
from __future__ import annotations

import asyncio
import base64
import re
from dataclasses import dataclass, asdict
from pathlib import Path

import httpx

from . import config, ffmpeg

EDGE_VOICES = {
    "edge:en-US-AndrewMultilingualNeural": "Andrew (US, warm male)",
    "edge:en-US-BrianMultilingualNeural": "Brian (US, casual male)",
    "edge:en-US-GuyNeural": "Guy (US, narrator male)",
    "edge:en-US-ChristopherNeural": "Christopher (US, deep male)",
    "edge:en-US-EricNeural": "Eric (US, male)",
    "edge:en-US-EmmaMultilingualNeural": "Emma (US, female)",
    "edge:en-US-JennyNeural": "Jenny (US, female)",
    "edge:en-US-AriaNeural": "Aria (US, expressive female)",
    "edge:en-US-AnaNeural": "Ana (US, child)",
    "edge:en-GB-RyanNeural": "Ryan (UK, male)",
    "edge:en-GB-SoniaNeural": "Sonia (UK, female)",
    "edge:en-AU-WilliamNeural": "William (AU, male)",
}
ELEVEN_VOICES = {
    "eleven:pNInz6obpgDQGcFmaJgB": "Adam (ElevenLabs)",
    "eleven:21m00Tcm4TlvDq8ikWAM": "Rachel (ElevenLabs)",
    "eleven:ErXwobaYiN019PkySvjV": "Antoni (ElevenLabs)",
    "eleven:EXAVITQu4vr4xnSDxMaL": "Bella (ElevenLabs)",
}
DEFAULT_VOICE = "edge:en-US-AndrewMultilingualNeural"


class TTSError(RuntimeError):
    pass


@dataclass
class Word:
    text: str
    start: float
    end: float

    def shifted(self, offset: float) -> "Word":
        return Word(self.text, self.start + offset, self.end + offset)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Speech:
    audio: Path  # mono 44.1k wav
    words: list[Word]
    duration: float


def list_voices() -> list[dict]:
    voices = [{"id": k, "name": v, "provider": "edge"} for k, v in EDGE_VOICES.items()]
    if config.elevenlabs_key():
        voices += [{"id": k, "name": v, "provider": "elevenlabs"} for k, v in ELEVEN_VOICES.items()]
    voices.append({"id": "silent", "name": "Silent (preview, no audio)", "provider": "silent"})
    return voices


def synthesize(text: str, voice: str, out_dir: Path, name: str, speed: float = 1.0) -> Speech:
    text = clean_text(text)
    if not text:
        raise TTSError("Nothing to say: text is empty")
    out_dir.mkdir(parents=True, exist_ok=True)
    wav = out_dir / f"{name}.wav"
    voice = voice or DEFAULT_VOICE
    if voice == "silent":
        words = estimate_timings(text, speed)
        dur = (words[-1].end if words else 0.5) + 0.15
        ffmpeg.silence(wav, dur)
        return Speech(wav, words, ffmpeg.duration(wav))
    if voice.startswith("edge:"):
        words = _edge(text, voice.split(":", 1)[1], out_dir / f"{name}.mp3", speed)
        ffmpeg.to_wav(out_dir / f"{name}.mp3", wav)
    elif voice.startswith("eleven:"):
        words = _eleven(text, voice.split(":", 1)[1], out_dir / f"{name}.mp3")
        if abs(speed - 1.0) > 0.01:
            ffmpeg.run(["-i", out_dir / f"{name}.mp3", "-filter:a", f"atempo={speed:.3f}",
                        "-ac", "1", "-ar", "44100", wav])
            words = [Word(w.text, w.start / speed, w.end / speed) for w in words]
        else:
            ffmpeg.to_wav(out_dir / f"{name}.mp3", wav)
    else:
        raise TTSError(f"Unknown voice '{voice}'")
    dur = ffmpeg.duration(wav)
    if not words:
        words = estimate_timings(text, speed, total=dur)
    return Speech(wav, words, dur)


def clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text


def estimate_timings(text: str, speed: float = 1.0, total: float | None = None) -> list[Word]:
    """Spread words over time proportionally to their length (used when a provider gives none)."""
    tokens = text.split()
    if not tokens:
        return []
    weights = [len(t) + 2 + (4 if t[-1] in ".!?" else 1 if t[-1] in ",;:" else 0) for t in tokens]
    if total is None:
        total = sum(weights) / (15.0 * max(speed, 0.1))  # ~15 weighted chars per second
    scale = total / sum(weights)
    words, t = [], 0.0
    for tok, w in zip(tokens, weights):
        d = w * scale
        words.append(Word(tok, round(t, 3), round(t + d * 0.85, 3)))
        t += d
    return words


def _edge(text: str, voice: str, mp3: Path, speed: float) -> list[Word]:
    try:
        import edge_tts
    except ImportError as e:  # pragma: no cover
        raise TTSError("edge-tts is not installed (pip install edge-tts)") from e

    rate = f"{round((speed - 1.0) * 100):+d}%"

    async def go() -> list[Word]:
        comm = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
        words: list[Word] = []
        with open(mp3, "wb") as f:
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    start = chunk["offset"] / 1e7
                    words.append(Word(chunk["text"], start, start + chunk["duration"] / 1e7))
        return words

    try:
        words = asyncio.run(go())
    except Exception as e:
        raise TTSError(f"Edge TTS failed ({e.__class__.__name__}: {e}). Check your internet connection "
                       "or pick another voice.") from e
    return _reattach_punctuation(text, words)


def _reattach_punctuation(text: str, words: list[Word]) -> list[Word]:
    """Edge word boundaries drop punctuation; map them back onto the source tokens when counts match."""
    tokens = text.split()
    if len(tokens) == len(words):
        return [Word(tok, w.start, w.end) for tok, w in zip(tokens, words)]
    return words


def _eleven(text: str, voice_id: str, mp3: Path) -> list[Word]:
    key = config.elevenlabs_key()
    if not key:
        raise TTSError("ELEVENLABS_API_KEY is not set")
    resp = httpx.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps",
        headers={"xi-api-key": key},
        json={"text": text, "model_id": "eleven_multilingual_v2"},
        timeout=120,
    )
    if resp.status_code != 200:
        raise TTSError(f"ElevenLabs error {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    mp3.write_bytes(base64.b64decode(data["audio_base64"]))
    al = data.get("alignment") or {}
    chars = al.get("characters") or []
    starts = al.get("character_start_times_seconds") or []
    ends = al.get("character_end_times_seconds") or []
    words: list[Word] = []
    cur, cs, ce = "", 0.0, 0.0
    for ch, s, e in zip(chars, starts, ends):
        if ch.isspace():
            if cur:
                words.append(Word(cur, cs, ce))
                cur = ""
            continue
        if not cur:
            cs = s
        cur += ch
        ce = e
    if cur:
        words.append(Word(cur, cs, ce))
    return words
