"""Centralised LLM calls using the OpenAI SDK (async client)."""

import json
import logging
import re

import openai

from config import Config

logger = logging.getLogger(__name__)

_client: openai.AsyncOpenAI | None = None
_model: str = ""


def init_llm(config: Config) -> None:
    """Initialise the async OpenAI client."""
    global _client, _model
    _client = openai.AsyncOpenAI(api_key=config.openai_api_key)
    _model = config.llm_model
    logger.info("LLM client initialised (model=%s).", _model)


async def answer_question(context: str, question: str) -> str:
    """Answer a question grounded in the provided context."""
    if _client is None:
        return "⚠️ LLM not initialised."

    try:
        response = await _client.chat.completions.create(
            model=_model,
            max_tokens=1024,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a helpful assistant for a small 2-person company. "
                        "Answer the user's question using ONLY the provided context "
                        "(chat history, notes, and decisions). "
                        "If the information isn't in the context, say so plainly — "
                        "do not make things up. Keep answers concise and direct."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"## Context\n\n{context}\n\n"
                        f"## Question\n\n{question}"
                    ),
                },
            ],
        )
        return response.choices[0].message.content
    except openai.APIError as exc:
        logger.exception("OpenAI API error")
        return f"⚠️ LLM API error: {exc.message}"
    except Exception as exc:
        logger.exception("Unexpected LLM error")
        return f"⚠️ Something went wrong talking to the LLM: {exc}"


async def parse_event(free_text: str, timezone: str) -> dict | None:
    """Parse free-text into calendar-event JSON via the LLM.

    Returns a dict with keys: title, start_iso, end_iso, location
    or None on failure.
    """
    if _client is None:
        return None

    try:
        response = await _client.chat.completions.create(
            model=_model,
            max_tokens=512,
            messages=[
                {
                    "role": "system",
                    "content": (
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
                },
                {"role": "user", "content": free_text},
            ],
        )
        raw = response.choices[0].message.content.strip()
        # Defensively strip stray code fences
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Failed to parse LLM response as JSON: %s", raw)
        return None
    except openai.APIError:
        logger.exception("OpenAI API error in parse_event")
        return None
    except Exception:
        logger.exception("Unexpected error in parse_event")
        return None
