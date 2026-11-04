"""AI clipping: find the moments of a long video that work best as standalone shorts."""
from __future__ import annotations

import re

from .. import config, llm, transcribe

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


def pick(segments: list[transcribe.Segment], total: float, count: int, min_len: float, max_len: float,
         use_ai: bool = True) -> tuple[list[dict], str, str | None]:
    """Return (clips, picker name, note). Uses Claude when available, else the local scorer."""
    note = None
    if use_ai and config.anthropic_enabled():
        try:
            clips = sanitize(llm.pick_highlights(format_transcript(segments), count, min_len, max_len),
                             total, min_len, max_len)[:count]
            if clips:
                return clips, "claude", None
        except Exception as e:  # fall back to the local scorer on any AI failure
            note = f"AI picker unavailable ({e}); used the built-in scorer"
    clips = sanitize(heuristic_highlights(segments, count, min_len, max_len), total, min_len, max_len)[:count]
    return clips, "heuristic", note
