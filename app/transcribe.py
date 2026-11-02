"""Speech-to-text with word timestamps via faster-whisper (loaded lazily, cached)."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from . import config
from .tts import Word

_model = None
_lock = threading.Lock()


class TranscriptionUnavailable(RuntimeError):
    pass


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: list[Word]


def _get_model():
    global _model
    with _lock:
        if _model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as e:
                raise TranscriptionUnavailable(
                    "faster-whisper is not installed; run `pip install faster-whisper` to enable "
                    "auto-captions and AI clipping") from e
            compute = "int8" if config.WHISPER_DEVICE == "cpu" else "float16"
            _model = WhisperModel(config.WHISPER_MODEL, device=config.WHISPER_DEVICE, compute_type=compute)
        return _model


def transcribe(media: Path, language: str | None = None) -> list[Segment]:
    model = _get_model()
    segments, _info = model.transcribe(str(media), word_timestamps=True, vad_filter=True, language=language)
    out: list[Segment] = []
    for seg in segments:
        words = [Word(w.word.strip(), float(w.start), float(w.end)) for w in (seg.words or []) if w.word.strip()]
        out.append(Segment(float(seg.start), float(seg.end), seg.text.strip(), words))
    return out


def words_between(segments: list[Segment], start: float, end: float) -> list[Word]:
    """All words inside [start, end], re-timed so ``start`` becomes 0."""
    return [w.shifted(-start) for s in segments for w in s.words if w.start >= start - 0.05 and w.end <= end + 0.05]
