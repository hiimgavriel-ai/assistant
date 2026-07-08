"""Centralised LLM calls using the Anthropic SDK (async client)."""

import json
import logging
import re

import anthropic

from config import Config

logger = logging.getLogger(__name__)

_client: anthropic.AsyncAnthropic | None = None
_model: str = ""


def init_llm(config: Config) -> None:
    """Initialise the async Anthropic client."""
    global _client, _model
    _client = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)
    _model = config.llm_model
    logger.info("LLM client initialised (model=%s).", _model)


async def answer_question(context: str, question: str) -> str:
    """Answer a question grounded in the provided context."""
    if _client is None:
        return "⚠️ LLM not initialised."

    try:
        response = await _client.messages.create(
            model=_model,
            max_tokens=1024,
            system=(
                "You are a helpful assistant for a small 2-person company. "
                "Answer the user's question using ONLY the provided context "
                "(chat history, notes, and decisions). "
                "If the information isn't in the context, say so plainly — "
                "do not make things up. Keep answers concise and direct."
            ),
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"## Context\n\n{context}\n\n"
                        f"## Question\n\n{question}"
                    ),
                }
            ],
        )
        return response.content[0].text
    except anthropic.APIError as exc:
        logger.exception("Anthropic API error")
        return f"⚠️ LLM API error: {exc.message}"
    except Exception as exc:
        logger.exception("Unexpected LLM error")
        return f"⚠️ Something went wrong talking to Claude: {exc}"


async def parse_event(free_text: str, timezone: str) -> dict | None:
    """Parse free-text into calendar-event JSON via Claude.

    Returns a dict with keys: title, start_iso, end_iso, location
    or None on failure.
    """
    if _client is None:
        return None

    try:
        response = await _client.messages.create(
            model=_model,
            max_tokens=512,
            system=(
                f"You are a calendar-event parser.  The user's timezone is {timezone}.\n"
                "Parse the user's free text into a calendar event.\n"
                "Return ONLY valid JSON — no markdown, no code fences, no prose.\n"
                "Fields:\n"
                "  • title  (string) — event title\n"
                "  • start_iso (string) — ISO 8601 datetime with timezone offset\n"
                "  • end_iso   (string) — ISO 8601 datetime with timezone offset\n"
                "  • location  (string) — location, or empty string if not specified\n\n"
                "If no end time is given, default to 1 hour after start.\n"
                f"Resolve all times to {timezone}."
            ),
            messages=[{"role": "user", "content": free_text}],
        )
        raw = response.content[0].text.strip()
        # Defensively strip stray code fences
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Failed to parse LLM response as JSON: %s", raw)
        return None
    except anthropic.APIError:
        logger.exception("Anthropic API error in parse_event")
        return None
    except Exception:
        logger.exception("Unexpected error in parse_event")
        return None
