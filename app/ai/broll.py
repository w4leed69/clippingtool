"""AI B-roll: find moments that benefit from cutaway footage and fetch matching clips.

Footage comes from Pexels (free stock video, needs PEXELS_API_KEY) or, without a key, from your own
B-roll library in data/broll/, matched by file name (e.g. ``city-night.mp4`` matches "city").
"""
from __future__ import annotations

import re
from pathlib import Path

import httpx

from .. import config, llm, media
from ..tts import Word

STOPWORDS = set("""a an the and or but so to of in on at for with from by is are was were be been being it this that
these those i you he she we they me my your our their his her them us do does did have has had not no yes just like
really very can could would should will about what when where who how why which there here then than also get got
going go know think make made one all some any more most other into out up down over again""".split())


def candidate_moments(words: list[Word], count: int, length: float = 2.5) -> list[dict]:
    """Fallback planner: evenly spaced moments, each labelled with the most specific nearby words."""
    if not words:
        return []
    total = words[-1].end
    if total < 6:
        return []
    count = max(1, min(count, int(total // 6)))
    out = []
    for k in range(count):
        center = total * (k + 1) / (count + 1)
        near = [w for w in words if abs(w.start - center) < 4]
        terms = [re.sub(r"[^a-z]", "", w.text.lower()) for w in near]
        terms = [t for t in terms if len(t) > 3 and t not in STOPWORDS]
        if not terms:
            continue
        query = " ".join(sorted(set(terms), key=lambda t: -len(t))[:2])
        start = max(0.5, center - length / 2)
        out.append({"start": round(start, 2), "end": round(min(total, start + length), 2), "query": query})
    return out


def library_moments(words: list[Word], count: int, length: float = 2.5) -> list[dict]:
    """Cut to a library clip whenever its name is spoken (``dog-park.mp4`` plays on "dog" or "park")."""
    keywords = {k for p in _local_library() for k in re.findall(r"[a-z]+", p.stem.lower())
                if len(k) > 2 and k not in STOPWORDS}
    out, last = [], -10.0
    total = words[-1].end if words else 0
    for w in words:
        k = re.sub(r"[^a-z]", "", w.text.lower())
        if k in keywords and w.start >= 1.0 and w.start - last >= 5:
            out.append({"start": round(w.start, 2), "end": round(min(total, w.start + length), 2), "query": k})
            last = w.start
            if len(out) >= count:
                break
    return out


def plan(words: list[Word], count: int, use_ai: bool = True) -> list[dict]:
    if not words:
        return []
    if use_ai and config.anthropic_enabled():
        try:
            transcript = " ".join(f"[{w.start:.1f}]{w.text}" for w in words)
            moments = llm.plan_broll(transcript, count, words[-1].end)
            if moments:
                return moments
        except Exception:
            pass
    moments = library_moments(words, count)
    if config.pexels_key() and len(moments) < count:  # fill the rest with stock footage
        for m in candidate_moments(words, count):
            if len(moments) >= count:
                break
            if all(m["end"] + 3 <= o["start"] or m["start"] >= o["end"] + 3 for o in moments):
                moments.append(m)
    return sorted(moments, key=lambda m: m["start"])


def _local_library() -> list[Path]:
    return [p for p in sorted(config.BROLL_DIR.iterdir()) if p.suffix.lower() in media.VIDEO_EXTS]


def _match_local(query: str, used: set[Path]) -> Path | None:
    q = set(re.findall(r"[a-z]+", query.lower()))
    best, best_score = None, 0
    for p in _local_library():
        name = set(re.findall(r"[a-z]+", p.stem.lower()))
        score = len(q & name) - (0.5 if p in used else 0)
        if score > best_score:
            best, best_score = p, score
    return best


def _pexels(query: str, dest: Path, portrait: bool) -> Path | None:
    key = config.pexels_key()
    if not key:
        return None
    r = httpx.get("https://api.pexels.com/videos/search", headers={"Authorization": key}, timeout=30,
                  params={"query": query, "per_page": 5, "orientation": "portrait" if portrait else "landscape",
                          "size": "medium"})
    if r.status_code != 200:
        return None
    for video in r.json().get("videos", []):
        files = [f for f in video.get("video_files", []) if f.get("file_type") == "video/mp4" and f.get("link")]
        files.sort(key=lambda f: abs((f.get("height") or 0) - 1280))
        if not files:
            continue
        with httpx.stream("GET", files[0]["link"], timeout=120, follow_redirects=True) as resp:
            if resp.status_code != 200:
                continue
            with open(dest, "wb") as f:
                for chunk in resp.iter_bytes():
                    f.write(chunk)
        return dest
    return None


def fetch(moments: list[dict], work: Path, portrait: bool = True) -> list[dict]:
    """Attach a ``path`` to each moment we found footage for; drop the rest."""
    found, used = [], set()
    for i, m in enumerate(moments):
        path = None
        try:
            path = _pexels(m["query"], work / f"broll{i}.mp4", portrait)
        except httpx.HTTPError:
            path = None
        if path is None:
            path = _match_local(m["query"], used)
        if path is not None:
            used.add(path)
            found.append({**m, "path": path})
    return found
