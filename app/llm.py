"""Claude-powered helpers: script writing and highlight picking. All return plain dicts."""
from __future__ import annotations

import json

from . import config


class LLMUnavailable(RuntimeError):
    pass


def structured(system: str, prompt: str | list, schema: dict, effort: str = "medium") -> dict:
    """One Claude call that must answer with JSON matching ``schema``.

    ``prompt`` is a string or a list of content blocks (text and images).
    """
    if not config.anthropic_enabled():
        raise LLMUnavailable("Set ANTHROPIC_API_KEY to use AI features")
    import anthropic

    client = anthropic.Anthropic()
    try:
        resp = client.beta.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            # If a request is declined by a safety classifier, let the API retry it on a fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.AuthenticationError as e:
        raise LLMUnavailable("Anthropic API key was rejected") from e
    except anthropic.RateLimitError as e:
        raise RuntimeError("Claude rate limit hit, try again in a moment") from e
    except anthropic.APIStatusError as e:
        raise RuntimeError(f"Claude API error {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise RuntimeError("Could not reach the Claude API") from e

    if resp.stop_reason == "refusal":
        raise RuntimeError("Claude declined this request; try rephrasing it")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("Claude's answer was cut off; try a shorter input")
    texts = [b.text for b in resp.content if b.type == "text"]
    if not texts:
        raise RuntimeError("Claude returned no text")
    return json.loads(texts[-1])


STORY_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Hooky first-person post title, under 120 characters"},
        "body": {"type": "string", "description": "The story itself, plain text, no markdown"},
    },
    "required": ["title", "body"],
    "additionalProperties": False,
}

CHAT_SCHEMA = {
    "type": "object",
    "properties": {
        "contact_name": {"type": "string"},
        "messages": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "sender": {"type": "string", "enum": ["me", "them"]},
                    "text": {"type": "string"},
                },
                "required": ["sender", "text"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["contact_name", "messages"],
    "additionalProperties": False,
}

WRITER_SYSTEM = (
    "You write scripts for short vertical videos (TikTok, Reels, Shorts) that are narrated by a text-to-speech "
    "voice. Open with a hook in the first sentence, keep sentences short and spoken-sounding, build tension, and "
    "end with a twist or a satisfying payoff. Never use markdown, emojis, hashtags, stage directions or "
    "parenthetical notes: every character you write will be read aloud or shown on screen. Keep it suitable "
    "for a general audience on mainstream platforms."
)


def write_story(idea: str, seconds: int = 60) -> dict:
    words = int(seconds * 2.6)
    prompt = (f"Write a first-person story post, the kind people share on story forums, for this idea:\n\n{idea}\n\n"
              f"The body should be about {words} words so the narration lasts roughly {seconds} seconds.")
    return structured(WRITER_SYSTEM, prompt, STORY_SCHEMA)


def write_chat(idea: str, messages: int = 14) -> dict:
    prompt = (f"Write a dramatic text-message conversation between 'me' and one contact for this idea:\n\n{idea}\n\n"
              f"Use about {messages} short messages (most under 15 words), in the way people really text. "
              "Give the contact a short display name. End on a punchline or twist.")
    return structured(WRITER_SYSTEM, prompt, CHAT_SCHEMA)


HIGHLIGHT_SCHEMA = {
    "type": "object",
    "properties": {
        "clips": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start": {"type": "number", "description": "Clip start in seconds"},
                    "end": {"type": "number", "description": "Clip end in seconds"},
                    "title": {"type": "string", "description": "Short catchy title for the clip"},
                    "hook": {"type": "string", "description": "Why this moment will grab viewers"},
                    "score": {"type": "integer", "description": "Predicted virality 1-100"},
                },
                "required": ["start", "end", "title", "hook", "score"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["clips"],
    "additionalProperties": False,
}


def pick_highlights(transcript: str, count: int, min_len: int, max_len: int) -> list[dict]:
    system = (
        "You are a short-form video editor. Given a timestamped transcript of a long video, you choose the "
        "moments that will perform best as standalone vertical clips: strong hook in the first 3 seconds, a "
        "complete thought or story, emotion, humor, surprising facts, or a clear payoff. Clips must start and "
        "end on sentence boundaries, must not overlap, and must make sense without the rest of the video."
    )
    prompt = (
        f"Pick the best {count} clips, each between {min_len} and {max_len} seconds long. Use the timestamps "
        f"exactly as given (seconds).\n\nTranscript:\n{transcript}"
    )
    return structured(system, prompt, HIGHLIGHT_SCHEMA)["clips"]


BROLL_SCHEMA = {
    "type": "object",
    "properties": {
        "moments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start": {"type": "number"},
                    "end": {"type": "number"},
                    "query": {"type": "string", "description": "2-4 word stock-footage search, concrete and visual"},
                },
                "required": ["start", "end", "query"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["moments"],
    "additionalProperties": False,
}


def plan_broll(transcript: str, count: int, duration: float) -> list[dict]:
    system = (
        "You are a video editor adding B-roll cutaways to a talking video. Pick moments where the speaker "
        "mentions something concrete and visual (a place, object, action, emotion) that stock footage can show. "
        "Each cutaway lasts 2 to 4 seconds, starts when the word is spoken, never in the first 2 seconds, "
        "and cutaways are at least 5 seconds apart."
    )
    prompt = (f"The clip is {duration:.1f} seconds long. Choose up to {count} B-roll moments. Each word below "
              f"is prefixed with its start time in seconds.\n\n{transcript}")
    moments = structured(system, prompt, BROLL_SCHEMA)["moments"]
    out = []
    for m in moments:
        s, e = max(0.0, float(m["start"])), min(duration, float(m["end"]))
        if 1.0 <= e - s <= 6 and m["query"].strip():
            out.append({"start": round(s, 2), "end": round(e, 2), "query": m["query"].strip()})
    return out[:count]


VOICEOVER_SCHEMA = {
    "type": "object",
    "properties": {"script": {"type": "string", "description": "Narration only, to be read aloud"}},
    "required": ["script"],
    "additionalProperties": False,
}


def write_voiceover(frames: list[str], duration: float, transcript: str = "", instructions: str = "") -> str:
    """Write narration for a clip from sampled frames (base64 JPEGs) plus any existing speech."""
    words = max(8, int(duration * 2.4))
    content: list = []
    for i, b64 in enumerate(frames):
        content.append({"type": "text", "text": f"Frame {i + 1} of {len(frames)}:"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}})
    ask = (f"These frames are evenly spaced through a {duration:.0f}-second video. Write a voice-over for it of "
           f"about {words} words so it fits the length. Describe and react to what happens, in order, with a hook "
           "in the first sentence.")
    if transcript:
        ask += f"\n\nWhat people say in the video (for context, do not just repeat it):\n{transcript}"
    if instructions:
        ask += f"\n\nCreator's instructions: {instructions}"
    content.append({"type": "text", "text": ask})
    return structured(WRITER_SYSTEM, content, VOICEOVER_SCHEMA)["script"].strip()


EMPHASIS_SCHEMA = {
    "type": "object",
    "properties": {"words": {"type": "array", "items": {"type": "string"}}},
    "required": ["words"],
    "additionalProperties": False,
}


def pick_emphasis(text: str) -> list[str]:
    """Words worth highlighting in captions (key nouns, numbers, emotional words)."""
    system = ("You style captions for short-form video. Pick the words that carry the meaning or emotion: key "
              "nouns, numbers, names, strong verbs and punchlines. About one word in eight, never filler words.")
    prompt = f"Return the words to emphasize, exactly as they appear in this transcript:\n\n{text}"
    return structured(system, prompt, EMPHASIS_SCHEMA, effort="low")["words"]
