"""Claude-powered helpers: script writing and highlight picking. All return plain dicts."""
from __future__ import annotations

import json

from . import config


class LLMUnavailable(RuntimeError):
    pass


def structured(system: str, prompt: str, schema: dict, effort: str = "medium") -> dict:
    """One Claude call that must answer with JSON matching ``schema``."""
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
