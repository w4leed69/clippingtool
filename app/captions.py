"""Animated word-by-word captions written as an ASS subtitle file (burned in by ffmpeg/libass)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import config
from .tts import Word


@dataclass(frozen=True)
class CaptionStyle:
    name: str
    label: str
    font_size: int
    text_color: str        # RRGGBB
    highlight_color: str   # RRGGBB (active word)
    outline_color: str = "000000"
    outline: int = 8
    shadow: int = 3
    uppercase: bool = True
    highlight: bool = True
    pop: bool = True
    max_words: int = 3


STYLES: dict[str, CaptionStyle] = {
    s.name: s
    for s in [
        CaptionStyle("bold", "Bold Yellow", 92, "FFFFFF", "FFE81F"),
        CaptionStyle("green", "Neon Green", 92, "FFFFFF", "39FF14"),
        CaptionStyle("pink", "Hot Pink", 92, "FFFFFF", "FF3EA5"),
        CaptionStyle("one", "One Word Punch", 120, "FFFFFF", "FFFFFF", max_words=1, highlight=False),
        CaptionStyle("clean", "Clean Minimal", 64, "FFFFFF", "FFFFFF", outline=4, shadow=2,
                     uppercase=False, highlight=False, pop=False, max_words=5),
    ]
}
DEFAULT_STYLE = "bold"


def list_styles() -> list[dict]:
    return [{"id": s.name, "name": s.label} for s in STYLES.values()]


def _ass_color(rrggbb: str, alpha: str = "00") -> str:
    r, g, b = rrggbb[0:2], rrggbb[2:4], rrggbb[4:6]
    return f"&H{alpha}{b}{g}{r}".upper()


def _ts(t: float) -> str:
    t = max(t, 0.0)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _escape(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def group_words(words: list[Word], max_words: int = 3, max_chars: int = 18, max_gap: float = 0.6) -> list[list[Word]]:
    groups: list[list[Word]] = []
    cur: list[Word] = []
    for w in words:
        if not w.text.strip():
            continue
        if cur:
            chars = sum(len(x.text) + 1 for x in cur) + len(w.text)
            ends_sentence = cur[-1].text[-1:] in ".!?,;:"
            gap = w.start - cur[-1].end
            if len(cur) >= max_words or chars > max_chars or ends_sentence or gap > max_gap:
                groups.append(cur)
                cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    return groups


def build_ass(words: list[Word], out: Path, style: str = DEFAULT_STYLE, y: float = 0.5,
              width: int = config.WIDTH, height: int = config.HEIGHT) -> Path:
    """Write an .ass file showing ``words`` in small animated groups, centered at ``y`` (0 top .. 1 bottom)."""
    st = STYLES.get(style, STYLES[DEFAULT_STYLE])
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Cap,{config.CAPTION_FONT},{st.font_size},{_ass_color(st.text_color)},&H000000FF,"
        f"{_ass_color(st.outline_color)},&H80000000,-1,0,0,0,100,100,0,0,1,{st.outline},{st.shadow},"
        f"5,80,80,0,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    px, py = width // 2, int(height * y)
    groups = group_words(words, max_words=st.max_words, max_chars=18 if st.max_words <= 3 else 32)
    for gi, group in enumerate(groups):
        group_end = group[-1].end
        if gi + 1 < len(groups):
            # keep the caption up until the next one starts (avoids flicker), but not across long pauses
            group_end = min(max(group_end, groups[gi + 1][0].start), group[-1].end + 0.6)
        texts = [_escape(w.text.upper() if st.uppercase else w.text) for w in group]
        slices = range(len(group)) if st.highlight else [None]
        for si in slices:
            start = group[si].start if si is not None else group[0].start
            if si is None:
                end = group_end
            else:
                end = group[si + 1].start if si + 1 < len(group) else group_end
            if end <= start:
                end = start + 0.05
            parts = []
            for wi, t in enumerate(texts):
                if si is not None and wi == si:
                    parts.append(f"{{\\c{_ass_color(st.highlight_color)}}}{t}{{\\c{_ass_color(st.text_color)}}}")
                else:
                    parts.append(t)
            anim = ""
            if st.pop and (si is None or si == 0):
                anim = "\\fscx75\\fscy75\\t(0,90,\\fscx108\\fscy108)\\t(90,160,\\fscx100\\fscy100)"
            text = f"{{\\pos({px},{py}){anim}}}" + " ".join(parts)
            lines.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Cap,,0,0,0,,{text}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out
