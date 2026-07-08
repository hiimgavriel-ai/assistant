"""Scheduled daily briefs — morning brief + Friday EOD open-task summary."""

import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from telegram.ext import ContextTypes

import gcal
from db import get_session
from models import Task, TaskStatus

logger = logging.getLogger(__name__)


async def morning_brief(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Post today's calendar events + open tasks to the group."""
    chat_id = context.job.chat_id
    tz_name = context.job.data.get("timezone", "Asia/Singapore")
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)

    lines: list[str] = [f"☀️ <b>Good morning! Here's your brief for {now.strftime('%A, %d %b %Y')}.</b>\n"]

    # ── Calendar events for today ────────────────────────────────────
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    try:
        events = await asyncio.to_thread(gcal.list_events, start, end)
    except Exception as exc:
        logger.exception("Morning brief: failed to fetch calendar events")
        events = []

    if events:
        lines.append("📅 <b>Today's Events</b>")
        for ev in events:
            summary = ev.get("summary", "(no title)")
            start_raw = ev.get("start", {})
            dt_str = start_raw.get("dateTime", start_raw.get("date", ""))
            time_display = _format_time(dt_str)
            loc = ev.get("location", "")
            line = f"  • <b>{time_display}</b> — {summary}"
            if loc:
                line += f"  📍 {loc}"
            lines.append(line)
    else:
        lines.append("📅 No events today — wide open schedule!")

    # ── Open tasks ───────────────────────────────────────────────────
    lines.append("")
    with get_session() as session:
        tasks = list(
            session.execute(
                select(Task)
                .where(Task.status == TaskStatus.open)
                .order_by(Task.created_at)
            ).scalars()
        )

    if tasks:
        lines.append(f"📋 <b>Open Tasks ({len(tasks)})</b>")
        for t in tasks:
            lines.append(f"  • #{t.id}  {t.description}")
    else:
        lines.append("📋 No open tasks — enjoy the day! 🎉")

    await context.bot.send_message(
        chat_id=chat_id,
        text="\n".join(lines),
        parse_mode="HTML",
    )
    logger.info("Morning brief posted to chat %s.", chat_id)


async def friday_eod(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Post open tasks going into next week (Friday 17:00)."""
    chat_id = context.job.chat_id

    with get_session() as session:
        tasks = list(
            session.execute(
                select(Task)
                .where(Task.status == TaskStatus.open)
                .order_by(Task.created_at)
            ).scalars()
        )

    if tasks:
        lines = [
            "🗓 <b>Open tasks going into next week</b>\n",
        ]
        for t in tasks:
            lines.append(f"  • #{t.id}  {t.description}")
        lines.append(f"\n<i>{len(tasks)} task(s) — have a great weekend!</i>")
    else:
        lines = ["🗓 <b>No open tasks going into next week — enjoy the weekend! 🎉</b>"]

    await context.bot.send_message(
        chat_id=chat_id,
        text="\n".join(lines),
        parse_mode="HTML",
    )
    logger.info("Friday EOD brief posted to chat %s.", chat_id)


def _format_time(iso_str: str) -> str:
    """Best-effort time formatting from an ISO string."""
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%I:%M %p")
    except Exception:
        return iso_str
