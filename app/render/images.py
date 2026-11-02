"""Pillow renderers: the story title card and chat-conversation screenshots."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .. import config

S = 2  # supersampling factor for smooth edges


@lru_cache(maxsize=64)
def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for path in (config.FONT_CANDIDATES_BOLD if bold else config.FONT_CANDIDATES_REGULAR):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt, max_width: int) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split():
            trial = f"{cur} {word}".strip()
            if draw.textlength(trial, font=fnt) <= max_width or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


def _line_h(fnt) -> int:
    asc, desc = fnt.getmetrics()
    return asc + desc


# --------------------------------------------------------------------------- story card

def story_card(title: str, out: Path, author: str = "storytime", community: str = "r/stories",
               upvotes: str = "99+", comments: str = "99+", dark: bool = False, width: int = 920) -> Path:
    """A generic social-post style title card (avatar, community, title, engagement row)."""
    W = width * S
    pad = 44 * S
    bg = (26, 26, 27) if dark else (255, 255, 255)
    fg = (240, 240, 240) if dark else (20, 20, 20)
    sub = (150, 150, 155) if dark else (110, 110, 115)
    accent = (255, 69, 0)

    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    f_title = font(50 * S, bold=True)
    f_name = font(34 * S, bold=True)
    f_meta = font(28 * S)
    lines = wrap(probe, title, f_title, W - 2 * pad)
    title_h = len(lines) * int(_line_h(f_title) * 1.08)
    avatar = 92 * S
    H = pad + avatar + 28 * S + title_h + 34 * S + 48 * S + pad

    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, W - 1, H - 1], radius=40 * S, fill=bg)

    # header
    d.ellipse([pad, pad, pad + avatar, pad + avatar], fill=accent)
    initial = (community.strip("r/") or "S")[0].upper()
    f_init = font(48 * S, bold=True)
    tw = d.textlength(initial, font=f_init)
    d.text((pad + (avatar - tw) / 2, pad + (avatar - _line_h(f_init)) / 2), initial, font=f_init, fill="white")
    x = pad + avatar + 24 * S
    d.text((x, pad + 6 * S), community, font=f_name, fill=fg)
    d.text((x, pad + 50 * S), f"u/{author} · 5h", font=f_meta, fill=sub)
    # verified badge
    bx = x + d.textlength(community, font=f_name) + 14 * S
    by = pad + 12 * S
    d.ellipse([bx, by, bx + 32 * S, by + 32 * S], fill=(29, 155, 240))
    d.line([bx + 8 * S, by + 17 * S, bx + 14 * S, by + 23 * S, bx + 24 * S, by + 10 * S], fill="white", width=4 * S)

    y = pad + avatar + 28 * S
    for line in lines:
        d.text((pad, y), line, font=f_title, fill=fg)
        y += int(_line_h(f_title) * 1.08)
    y += 34 * S

    # engagement row: heart + count, bubble + count, share arrow
    icon = 40 * S
    cx = pad
    d.polygon(_heart(cx, y, icon), fill=(249, 24, 128))
    d.text((cx + icon + 12 * S, y + 2 * S), upvotes, font=f_meta, fill=sub)
    cx += icon + 40 * S + d.textlength(upvotes, font=f_meta) + 30 * S
    d.rounded_rectangle([cx, y + 2 * S, cx + icon, y + icon - 6 * S], radius=12 * S, outline=sub, width=4 * S)
    d.polygon([(cx + 8 * S, y + icon - 8 * S), (cx + 8 * S, y + icon + 4 * S), (cx + 20 * S, y + icon - 8 * S)], fill=sub)
    d.text((cx + icon + 12 * S, y + 2 * S), comments, font=f_meta, fill=sub)
    sx = W - pad - icon
    d.line([sx, y + icon - 4 * S, sx + icon / 2, y + 4 * S, sx + icon, y + icon - 4 * S], fill=sub, width=5 * S)

    img = img.resize((W // S, H // S), Image.LANCZOS)
    img.save(out)
    return out


def _heart(x: float, y: float, s: float) -> list[tuple[float, float]]:
    import math
    pts = []
    for i in range(60):
        t = 2 * math.pi * i / 60
        hx = 16 * math.sin(t) ** 3
        hy = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        pts.append((x + s / 2 + hx * s / 34, y + s / 2 - hy * s / 34))
    return pts


# --------------------------------------------------------------------------- chat screenshots

CHAT_THEMES = {
    "light": {"bg": (255, 255, 255), "header": (246, 246, 248), "them": (233, 233, 235), "them_fg": (0, 0, 0),
              "me": (10, 132, 255), "me_fg": (255, 255, 255), "name": (0, 0, 0), "sub": (142, 142, 147)},
    "dark": {"bg": (0, 0, 0), "header": (28, 28, 30), "them": (38, 38, 41), "them_fg": (255, 255, 255),
             "me": (10, 132, 255), "me_fg": (255, 255, 255), "name": (255, 255, 255), "sub": (142, 142, 147)},
    "green": {"bg": (255, 255, 255), "header": (246, 246, 248), "them": (233, 233, 235), "them_fg": (0, 0, 0),
              "me": (52, 199, 89), "me_fg": (255, 255, 255), "name": (0, 0, 0), "sub": (142, 142, 147)},
}


def chat_frame(messages: list[dict], contact: str, out: Path, theme: str = "light",
               width: int = 940, max_height: int = 1250) -> Path:
    """Render a phone-style chat screen showing ``messages`` (each {'sender': 'me'|'them', 'text': str}).

    When the conversation is taller than ``max_height`` only the most recent messages are kept,
    like a chat that has scrolled.
    """
    th = CHAT_THEMES.get(theme, CHAT_THEMES["light"])
    W, maxH = width * S, max_height * S
    pad = 34 * S
    header_h = 190 * S
    f_msg = font(40 * S)
    f_name = font(32 * S, bold=True)
    bubble_max = int(W * 0.72)
    inner = 30 * S
    gap_same, gap_diff = 8 * S, 22 * S
    lh = int(_line_h(f_msg) * 1.05)
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    bubbles = []
    for m in messages:
        lines = wrap(probe, m["text"], f_msg, bubble_max - 2 * inner)
        tw = max(probe.textlength(line, font=f_msg) for line in lines) if lines else 0
        bw = int(tw + 2 * inner)
        bh = int(len(lines) * lh + 2 * 20 * S)
        bubbles.append((m["sender"] == "me", lines, bw, bh))

    # keep the newest bubbles that fit
    avail = maxH - header_h - 2 * pad
    used, start = 0, len(bubbles)
    for i in range(len(bubbles) - 1, -1, -1):
        gap = 0 if i == len(bubbles) - 1 else (gap_same if bubbles[i][0] == bubbles[i + 1][0] else gap_diff)
        if used + bubbles[i][3] + gap > avail and start < len(bubbles):
            break
        used += bubbles[i][3] + gap
        start = i
    shown = bubbles[start:]
    H = header_h + pad + used + pad + 10 * S

    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, W - 1, H - 1], radius=48 * S, fill=th["bg"])
    d.rounded_rectangle([0, 0, W - 1, header_h], radius=48 * S, fill=th["header"])
    d.rectangle([0, header_h - 48 * S, W - 1, header_h], fill=th["header"])
    d.line([0, header_h, W, header_h], fill=(200, 200, 204) if theme != "dark" else (56, 56, 58), width=2 * S)

    # header: back chevron, avatar with initial, contact name
    d.line([pad + 18 * S, 70 * S, pad, 92 * S, pad + 18 * S, 114 * S], fill=(10, 132, 255), width=6 * S)
    av = 92 * S
    ax = (W - av) // 2
    d.ellipse([ax, 26 * S, ax + av, 26 * S + av], fill=(160, 165, 178))
    f_init = font(44 * S, bold=True)
    initial = (contact.strip() or "?")[0].upper()
    tw = d.textlength(initial, font=f_init)
    d.text((ax + (av - tw) / 2, 26 * S + (av - _line_h(f_init)) / 2), initial, font=f_init, fill="white")
    nw = d.textlength(contact, font=f_name)
    d.text(((W - nw) / 2, 128 * S), contact, font=f_name, fill=th["name"])

    y = header_h + pad
    for idx, (mine, lines, bw, bh) in enumerate(shown):
        if idx > 0:
            y += gap_same if shown[idx - 1][0] == mine else gap_diff
        x0 = W - pad - bw if mine else pad
        color = th["me"] if mine else th["them"]
        fg = th["me_fg"] if mine else th["them_fg"]
        d.rounded_rectangle([x0, y, x0 + bw, y + bh], radius=40 * S, fill=color)
        last_of_run = idx == len(shown) - 1 or shown[idx + 1][0] != mine
        if last_of_run:  # tail
            if mine:
                d.polygon([(x0 + bw - 30 * S, y + bh - 34 * S), (x0 + bw + 12 * S, y + bh),
                           (x0 + bw - 46 * S, y + bh)], fill=color)
            else:
                d.polygon([(x0 + 30 * S, y + bh - 34 * S), (x0 - 12 * S, y + bh),
                           (x0 + 46 * S, y + bh)], fill=color)
        ty = y + 20 * S
        for line in lines:
            d.text((x0 + inner, ty), line, font=f_msg, fill=fg)
            ty += lh
        y += bh

    img = img.resize((W // S, H // S), Image.LANCZOS)
    img.save(out)
    return out
