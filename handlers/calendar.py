"""Calendar handlers — /planevent (with confirm/cancel), /agenda."""

import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import gcal
from config import Config
from handlers import safe_handler
from handlers.security import whitelist_only
from llm import parse_event

logger = logging.getLogger(__name__)

_timezone: str = "Asia/Singapore"


def init_calendar_handlers(config: Config) -> None:
    global _timezone
    _timezone = config.timezone


# ── /planevent ──────────────────────────────────────────────────────────


@safe_handler
@whitelist_only
async def planevent_cmd(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """/planevent <free text> — parse a calendar event via LLM and preview it."""
    text = " ".join(context.args) if context.args else ""
    if not text.strip():
        await update.message.reply_text(
            "Usage: /planevent <free text>\n"
            "Example: /planevent 30 July 2026 CCK Secondary Workshop 3pm"
        )
        return

    await update.message.reply_text("📅 Parsing your event…")

    event_data = await parse_event(text, _timezone)
    if event_data is None:
        await update.message.reply_text(
            "⚠️ Couldn't parse that into a calendar event. "
            "Try rephrasing with a clearer date/time."
        )
        return

    title = event_data.get("title", "(no title)")
    start = event_data.get("start_iso", "?")
    end = event_data.get("end_iso", "?")
    location = event_data.get("location", "")

    preview_lines = [
        "📅 <b>Event Preview</b>\n",
        f"<b>Title:</b>  {title}",
        f"<b>Start:</b>  {_format_iso(start)}",
        f"<b>End:</b>    {_format_iso(end)}",
    ]
    if location:
        preview_lines.append(f"<b>Location:</b> {location}")

    # Store pending event data keyed by the user's original message id
    key = f"pending_event:{update.message.message_id}"

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Create", callback_data=f"evt_create:{key}"),
                InlineKeyboardButton("✏️ Cancel", callback_data=f"evt_cancel:{key}"),
            ]
        ]
    )

    sent = await update.message.reply_text(
        "\n".join(preview_lines),
        parse_mode="HTML",
        reply_markup=keyboard,
    )

    # Save event data in chat_data so the callback can retrieve it
    context.chat_data[key] = event_data
    logger.info("Pending event stored under key %s.", key)


# ── Confirm / Cancel callbacks ──────────────────────────────────────────


@safe_handler
async def event_confirm_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle the ✅ Create button for /planevent."""
    query = update.callback_query
    await query.answer()

    # Security check
    from handlers.security import _allowed_chat_id

    if _allowed_chat_id is not None and query.message.chat.id != _allowed_chat_id:
        return

    key = query.data.split(":", 1)[1]
    event_data = context.chat_data.pop(key, None)

    if event_data is None:
        await query.edit_message_text("⚠️ Event data expired. Please run /planevent again.")
        return

    try:
        created = await asyncio.to_thread(
            gcal.create_event,
            title=event_data.get("title", "Untitled"),
            start_iso=event_data["start_iso"],
            end_iso=event_data["end_iso"],
            location=event_data.get("location", ""),
        )
        link = created.get("htmlLink", "")
        await query.edit_message_text(
            f"✅ Event created!\n🔗 <a href=\"{link}\">Open in Google Calendar</a>",
            parse_mode="HTML",
        )
    except Exception as exc:
        logger.exception("Failed to create Google Calendar event")
        await query.edit_message_text(f"⚠️ Failed to create event: {exc}")


@safe_handler
async def event_cancel_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle the ✏️ Cancel button for /planevent."""
    query = update.callback_query
    await query.answer()

    key = query.data.split(":", 1)[1]
    context.chat_data.pop(key, None)

    await query.edit_message_text("❌ Event creation cancelled.")


# ── /agenda ──────────────────────────────────────────────────────────────


@safe_handler
@whitelist_only
async def agenda_cmd(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """/agenda [tomorrow|week] — list upcoming calendar events."""
    arg = context.args[0].lower() if context.args else ""
    tz = ZoneInfo(_timezone)
    now = datetime.now(tz)

    if arg == "tomorrow":
        start = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        label = "tomorrow"
    elif arg == "week":
        start = now
        end = (now + timedelta(days=7)).replace(hour=23, minute=59, second=59)
        label = "the next 7 days"
    else:
        # Rest of today
        start = now
        end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        label = "the rest of today"

    try:
        events = await asyncio.to_thread(gcal.list_events, start, end)
    except Exception as exc:
        logger.exception("Failed to fetch calendar events")
        await update.message.reply_text(f"⚠️ Calendar error: {exc}")
        return

    if not events:
        await update.message.reply_text(f"📅 No events for {label}.")
        return

    lines = [f"📅 <b>Agenda — {label}</b>\n"]
    for ev in events:
        summary = ev.get("summary", "(no title)")
        start_raw = ev.get("start", {})
        dt_str = start_raw.get("dateTime", start_raw.get("date", ""))
        time_display = _format_iso(dt_str)
        location = ev.get("location", "")
        line = f"• <b>{time_display}</b> — {summary}"
        if location:
            line += f"  📍 {location}"
        lines.append(line)

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ── Helpers ──────────────────────────────────────────────────────────────


def _format_iso(iso_str: str) -> str:
    """Attempt to format an ISO datetime string into a readable form."""
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%a %d %b %Y, %I:%M %p")
    except Exception:
        return iso_str
