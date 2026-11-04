# ClipForge

A self-hosted AI video editor for short-form content (TikTok, Reels, Shorts). Upload one video, turn on the AI tools you want, and get ready-to-post clips. Everything renders on your own machine with ffmpeg.

## AI Studio

| Feature | What it does |
| --- | --- |
| **AI clipping** | Transcribes a long video and picks the moments most likely to go viral, each with a title and a score. Uses Claude, or a built-in scorer without an API key |
| **AI captions** | Word-by-word animated captions with key words highlighted, plus an `.srt` file you can download |
| **AI reframe** | Tracks the speaker's face and moves a virtual camera smoothly to keep them in frame (9:16, 1:1 or 16:9). Also offers blurred fill, center crop, split screen with gameplay, or the original framing |
| **AI B-roll** | Cuts to matching footage when something visual is mentioned. Footage comes from Pexels (free, needs `PEXELS_API_KEY`) or from your own clips in `data/broll/`, matched by file name (`city-night.mp4` plays on "city") |
| **AI audio enhance** | Removes noise and hum, tames harsh "s" sounds, evens out the voice and normalizes to the -14 LUFS loudness short-video platforms use |
| **AI voice-over** | Claude looks at frames from your clip, writes narration that fits its length, and a voice reads it. The original audio either drops in volume under the voice or is replaced. You can also write the script yourself |

You can turn each feature on or off separately. The **Story video** and **Text story** templates are still there for faceless content.

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
| `ANTHROPIC_API_KEY` | Turns on Claude for clip picking, voice-over scripts, B-roll planning, caption highlights and the script writer |
| `CLAUDE_MODEL` | Defaults to `claude-opus-5-5` |
| `PEXELS_API_KEY` | Free stock footage for AI B-roll ([get a key](https://www.pexels.com/api/)) |
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
| `POST /api/jobs/studio` | `upload_id\|url, clip, clip_count, clip_min, clip_max, reframe: ai\|blur\|center\|split\|none, aspect, captions, caption_style, broll, broll_count, enhance, voiceover, vo_mode: duck\|replace, vo_script, vo_voice` |
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
  llm.py             Claude calls (structured JSON output): clips, voice-over, B-roll, emphasis, scripts
  ai/                highlights (clipping), reframe (face tracking), broll, audio (enhance + voice-over mix)
  media.py           background/music library, uploads, URL downloads
  render/images.py   title card + chat screen renderer (Pillow)
  pipelines/         studio (all AI features), story, chat, shared ffmpeg compositions
  static/            web UI (no build step)
tests/               pytest suite (renders real videos with the silent voice)
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```
