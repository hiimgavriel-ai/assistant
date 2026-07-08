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


# ── /help command ───────────────────────────────────────────────────────

_HELP_TEXT = (
    "🤖 <b>Company Assistant — Command Reference</b>\n"
    "\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n"
    "📋 <b>Tasks</b>\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n"
    "<code>/task &lt;text&gt;</code> — Create a new task\n"
    "  <i>Example:</i> <code>/task Buy domain for the project</code>\n"
    "  <i>Tip:</i> Reply to any message with <code>/task</code> to promote it\n"
    "\n"
    "<code>/tasks</code> — List all open tasks with ✅ Done buttons\n"
    "\n"
    "<code>/done &lt;id&gt;</code> — Mark a task done by ID\n"
    "  <i>Example:</i> <code>/done 3</code>\n"
    "\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n"
    "🧠 <b>Second Brain</b>\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n"
    "<code>/note &lt;text&gt;</code> — Save a high-signal note\n"
    "  <i>Example:</i> <code>/note We agreed to use Stripe</code>\n"
    "\n"
    "<code>/decision &lt;text&gt;</code> — Record a decision\n"
    "  <i>Example:</i> <code>/decision Go with the 3-month timeline</code>\n"
    "\n"
    "<code>/ask &lt;question&gt;</code> — Ask a question about your company history\n"
    "  <i>Example:</i> <code>/ask What payment provider did we choose?</code>\n"
    "\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n"
    "📅 <b>Calendar</b>\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n"
    "<code>/planevent &lt;free text&gt;</code> — Create a calendar event from natural language\n"
    "  <i>Example:</i> <code>/planevent 30 July 2026 Workshop 3pm</code>\n"
    "\n"
    "<code>/agenda</code> — Today's remaining events\n"
    "<code>/agenda tomorrow</code> — Tomorrow's events\n"
    "<code>/agenda week</code> — Next 7 days\n"
    "\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n"
    "🔧 <b>Utility</b>\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n"
    "<code>/chatid</code> — Show this chat's ID (for setup)\n"
    "<code>/help</code> — Show this message\n"
)


@safe_handler
@whitelist_only
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/help — show all available commands."""
    await update.message.reply_text(_HELP_TEXT, parse_mode="HTML")


# ── Welcome new members ────────────────────────────────────────────────


@safe_handler
@whitelist_only
async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Greet human users who join the allowed group."""
    for member in update.message.new_chat_members:
        if member.is_bot:
            continue
        await update.message.reply_text(
            f"👋 Welcome, <b>{member.first_name}</b>!\n\n"
            "I'm the company assistant bot — I help manage "
            "<b>tasks</b>, <b>notes &amp; decisions</b>, and "
            "<b>calendar events</b> right here in the chat.\n\n"
            "Type /help to see everything I can do.",
            parse_mode="HTML",
        )
