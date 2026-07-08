"""Task management handlers — /task, /tasks, /done, and done-button callback."""

import logging
from datetime import datetime, timezone as _tz

from sqlalchemy import select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from db import get_session
from handlers import safe_handler
from handlers.security import whitelist_only
from models import Task, TaskStatus

logger = logging.getLogger(__name__)


# ── /task ────────────────────────────────────────────────────────────────


@safe_handler
@whitelist_only
async def task_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/task <text>  — create a task.
    Replying to a message with just /task promotes that message into a task.
    """
    text = " ".join(context.args) if context.args else ""

    # If no inline text, check for a reply
    if not text and update.message.reply_to_message:
        text = update.message.reply_to_message.text or ""

    if not text.strip():
        await update.message.reply_text(
            "Usage:\n"
            "• /task <description>\n"
            "• Reply to any message with /task"
        )
        return

    user = update.effective_user
    with get_session() as session:
        task = Task(
            description=text.strip(),
            created_by_id=user.id,
            created_by_name=user.full_name,
        )
        session.add(task)
        session.commit()
        task_id = task.id

    await update.message.reply_text(
        f"✅ Task <b>#{task_id}</b> created:\n<i>{text.strip()}</i>",
        parse_mode="HTML",
    )
    logger.info("Task #%s created by %s.", task_id, user.full_name)


# ── /tasks ───────────────────────────────────────────────────────────────


@safe_handler
@whitelist_only
async def tasks_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/tasks — list all open tasks with ✅ Done buttons."""
    with get_session() as session:
        tasks = list(
            session.execute(
                select(Task)
                .where(Task.status == TaskStatus.open)
                .order_by(Task.created_at)
            ).scalars()
        )

    if not tasks:
        await update.message.reply_text("🎉 No open tasks — you're all caught up!")
        return

    lines: list[str] = ["📋 <b>Open Tasks</b>\n"]
    keyboard: list[list[InlineKeyboardButton]] = []

    for t in tasks:
        lines.append(f"<b>#{t.id}</b>  {t.description}")
        keyboard.append(
            [InlineKeyboardButton(f"✅ Done #{t.id}", callback_data=f"task_done:{t.id}")]
        )

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ── /done <id> ───────────────────────────────────────────────────────────


@safe_handler
@whitelist_only
async def done_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/done <id> — mark a task done by ID (text fallback for the button)."""
    if not context.args:
        await update.message.reply_text("Usage: /done <task_id>")
        return

    try:
        task_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("⚠️ Task ID must be a number.")
        return

    result = _mark_done(task_id, update.effective_user.full_name)
    await update.message.reply_text(result, parse_mode="HTML")


# ── Inline callback for the ✅ Done button ──────────────────────────────


@safe_handler
async def task_done_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle presses on the ✅ Done inline button."""
    query = update.callback_query
    await query.answer()

    # Security: verify chat
    from handlers.security import _allowed_chat_id

    if _allowed_chat_id is not None and query.message.chat.id != _allowed_chat_id:
        return

    task_id = int(query.data.split(":")[1])
    user_name = query.from_user.full_name

    result = _mark_done(task_id, user_name)

    # Rebuild the task list message in-place
    with get_session() as session:
        tasks = list(
            session.execute(
                select(Task)
                .where(Task.status == TaskStatus.open)
                .order_by(Task.created_at)
            ).scalars()
        )

    if tasks:
        lines: list[str] = ["📋 <b>Open Tasks</b>\n"]
        keyboard: list[list[InlineKeyboardButton]] = []
        for t in tasks:
            lines.append(f"<b>#{t.id}</b>  {t.description}")
            keyboard.append(
                [InlineKeyboardButton(f"✅ Done #{t.id}", callback_data=f"task_done:{t.id}")]
            )
        lines.append(f"\n<i>✔ {result}</i>")
        try:
            await query.edit_message_text(
                "\n".join(lines),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        except Exception:
            pass  # message may already be identical
    else:
        try:
            await query.edit_message_text(
                f"🎉 All tasks done!\n\n<i>✔ {result}</i>",
                parse_mode="HTML",
            )
        except Exception:
            pass


# ── Helpers ──────────────────────────────────────────────────────────────


def _mark_done(task_id: int, user_name: str) -> str:
    """Mark a task as done. Returns a human-friendly result string."""
    with get_session() as session:
        task = session.get(Task, task_id)
        if task is None:
            return f"⚠️ Task #{task_id} not found."
        if task.status == TaskStatus.done:
            return f"Task #{task_id} was already done."

        task.status = TaskStatus.done
        task.done_by_name = user_name
        task.done_at = datetime.now(_tz.utc)
        session.commit()
        logger.info("Task #%s marked done by %s.", task_id, user_name)
        return f"Task <b>#{task_id}</b> marked done by {user_name}."
