# ClipForge

A self-hosted generator for short vertical videos (TikTok, Reels, Shorts). You can make narrated story videos, fake text-message stories, split-screen gameplay edits, and AI-picked clips from long videos. Everything renders locally with ffmpeg.

| Tool | What it makes |
| --- | --- |
| **Story video** | Title card, voiceover and animated word-by-word captions over background gameplay. Can split long stories into Part 1, 2, 3… |
| **Text story** | A chat conversation that appears one bubble at a time, with each side read by its own voice |
| **Split screen** | Your clip on top, gameplay underneath, auto captions |
| **Blur reframe** | A horizontal video made vertical with a blurred fill and auto captions |
| **AI clipper** | Turns a long video or podcast into several captioned shorts. Claude picks the best moments (a built-in scorer is used if no API key is set) |
| **AI writer** | Writes a story or chat script from a one-line idea (Claude) |

All output is 1080×1920, 30 fps, H.264/AAC MP4.

## Quick start

Requirements: Python 3.10+ and ffmpeg (built with libass, which standard builds include).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # optional: add ANTHROPIC_API_KEY / ELEVENLABS_API_KEY
uvicorn app.main:app --port 8000
```

Then open http://localhost:8000.

On first start the app generates three placeholder backgrounds, so it works right away. To add your own gameplay footage or music, use the **Library** tab or drop `.mp4` files into `data/backgrounds/` (and audio into `data/music/`). Only use footage and music you have the rights to use.

## Configuration (`.env`)

| Variable | Purpose |
| --- | --- |
| `ANTHROPIC_API_KEY` | Turns on the AI script writer and AI highlight picking |
| `CLAUDE_MODEL` | Defaults to `claude-opus-5-5` |
| `ELEVENLABS_API_KEY` | Adds ElevenLabs voices. Without it, free Microsoft Edge neural voices are used |
| `WHISPER_MODEL` / `WHISPER_DEVICE` | faster-whisper size (`base` by default) and `cpu`/`cuda`, used for captions and clipping |
| `DATA_DIR` | Where uploads, the library and rendered videos are stored (`./data`) |
| `MAX_WORKERS` | Number of renders that run in parallel |

Voices: Edge voices need internet access. The **Silent** voice renders without audio, which is useful for quickly checking layouts.

## API

Every generator is a background job. You POST to create it and then poll it.

```bash
curl -X POST localhost:8000/api/jobs/story -H 'content-type: application/json' -d '{
  "title": "I found out my roommate has a secret twin",
  "body": "So this started last week...",
  "voice": "edge:en-US-AndrewMultilingualNeural",
  "caption_style": "bold"
}'
curl localhost:8000/api/jobs/<id>     # status, progress, outputs[].url
```

| Endpoint | Body |
| --- | --- |
| `POST /api/jobs/story` | `title, body, voice, speed, background, music, caption_style, caption_y, part_seconds` |
| `POST /api/jobs/chat` | `contact_name, messages[{sender: me\|them, text}], hook, voice_me, voice_them, theme` |
| `POST /api/jobs/edit` | `upload_id\|url, layout: split\|blur\|crop, captions, start, end` |
| `POST /api/jobs/clip` | `upload_id\|url, count, min_seconds, max_seconds, layout, use_ai` |
| `POST /api/uploads` | multipart `file`, returns `{id}` to use as `upload_id` |
| `POST /api/ai/script` | `kind: story\|chat, idea, seconds` |
| `GET /api/meta` | voices, caption styles, backgrounds, music |

Interactive docs are at `/docs`.

## Project layout

```
app/
  main.py            FastAPI routes + request validation
  jobs.py            background job queue (JSON-persisted)
  tts.py             TTS providers with word timings (Edge, ElevenLabs, silent)
  captions.py        animated ASS captions (word highlight + pop)
  transcribe.py      faster-whisper word timestamps
  llm.py             Claude: script writer + highlight picker (structured JSON output)
  media.py           background/music library, uploads, URL downloads
  render/images.py   title card + chat screen renderer (Pillow)
  pipelines/         story, chat, edit (split/blur), clipper, shared ffmpeg compositions
  static/            web UI (no build step)
tests/               pytest suite (renders real videos with the silent voice)
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```
