"""Shared handler utilities — error-safe wrapper decorator."""

import functools
import logging
from typing import Callable, Coroutine, Any

from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


def safe_handler(func: Callable[..., Coroutine[Any, Any, Any]]):
    """Decorator that catches exceptions in a handler, logs them,
    and sends a short error notice to the chat so the bot keeps running."""

    @functools.wraps(func)
    async def wrapper(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> Any:
        try:
            return await func(update, context)
        except Exception as exc:
            logger.exception("Error in handler %s: %s", func.__name__, exc)
            try:
                chat = update.effective_chat
                if chat:
                    await context.bot.send_message(
                        chat_id=chat.id,
                        text=(
                            f"⚠️ Something went wrong: {exc}\n\n"
                            "The bot is still running — please try again."
                        ),
                    )
            except Exception:
                logger.exception(
                    "Failed to send error notice for handler %s", func.__name__
                )

    return wrapper
