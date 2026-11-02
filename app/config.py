"""Runtime configuration, read from environment variables (and an optional .env file)."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if value and key not in os.environ:
            os.environ[key] = value


_load_dotenv()

DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT / "data")).resolve()
UPLOADS_DIR = DATA_DIR / "uploads"
BACKGROUNDS_DIR = DATA_DIR / "backgrounds"
MUSIC_DIR = DATA_DIR / "music"
OUTPUTS_DIR = DATA_DIR / "outputs"
WORK_DIR = DATA_DIR / "work"
JOBS_DIR = DATA_DIR / "jobs"

for _d in (UPLOADS_DIR, BACKGROUNDS_DIR, MUSIC_DIR, OUTPUTS_DIR, WORK_DIR, JOBS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

WIDTH = 1080
HEIGHT = 1920
FPS = 30

CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "base")
WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "2"))

# Fonts tried in order for images drawn with Pillow (reddit cards, chat bubbles).
FONT_CANDIDATES_BOLD = [
    "/usr/share/fonts/opentype/inter/Inter-Bold.otf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]
FONT_CANDIDATES_REGULAR = [
    "/usr/share/fonts/opentype/inter/Inter-Regular.otf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "C:/Windows/Fonts/arial.ttf",
]
# Font family name handed to libass for burned-in captions (fontconfig falls back if missing).
CAPTION_FONT = os.environ.get("CAPTION_FONT", "Inter")


def anthropic_enabled() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def elevenlabs_key() -> str | None:
    return os.environ.get("ELEVENLABS_API_KEY") or None
