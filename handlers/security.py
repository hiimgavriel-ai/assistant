"""Security layer — chat-ID whitelist guard and /chatid discovery command."""

import functools
import logging
from typing import Any, Callable, Coroutine

from telegram import Update
from telegram.ext import ContextTypes

from config import Config
from handlers import safe_handler

logger = logging.getLogger(__name__)

_allowed_chat_id: int | None = None


def init_security(config: Config) -> None:
    """Store the allowed chat ID for the whitelist guard."""
    global _allowed_chat_id
    _allowed_chat_id = config.allowed_chat_id


# ── Whitelist decorator ─────────────────────────────────────────────────


def whitelist_only(func: Callable[..., Coroutine[Any, Any, Any]]):
    """Decorator: silently ignores updates that don't come from the
    allowed chat.  If ALLOWED_CHAT_ID is unset, blocks everything."""

    @functools.wraps(func)
    async def wrapper(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> Any:
        chat = update.effective_chat
        if chat is None:
            return

        # Always log the chat ID at INFO for discovery
        logger.info(
            "Incoming update from chat_id=%s (user=%s).",
            chat.id,
            getattr(update.effective_user, "full_name", "?"),
        )

        if _allowed_chat_id is None:
            # First-deploy mode — only /chatid is allowed (handled separately)
            if update.effective_message:
                await update.effective_message.reply_text(
                    "🔒 Bot is not configured yet.\n"
                    "Use /chatid to discover this chat's ID, "
                    "then set ALLOWED_CHAT_ID and redeploy."
                )
            return

        if chat.id != _allowed_chat_id:
            logger.debug("Ignoring update from non-allowed chat %s.", chat.id)
            return  # silently ignore

        return await func(update, context)

    return wrapper


# ── /chatid command (bypasses whitelist) ────────────────────────────────


@safe_handler
async def chatid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/chatid — replies with the current chat's integer ID."""
    chat = update.effective_chat
    if chat is None:
        return
    logger.info("/chatid invoked in chat_id=%s", chat.id)
    await update.message.reply_text(
        f"💬 This chat's ID is: <code>{chat.id}</code>\n\n"
        "Copy this value into the <b>ALLOWED_CHAT_ID</b> environment variable.",
        parse_mode="HTML",
    )
