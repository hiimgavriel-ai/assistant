"""Task management handlers — /task, /tasks, /done, /braindump and callbacks."""

import logging
from datetime import datetime, timezone as _tz

from sqlalchemy import select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from db import get_session
from handlers import safe_handler
from handlers.security import whitelist_only
from llm import extract_tasks
from models import Task, TaskStatus

logger = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────────────────


def _format_task_line(t: Task) -> str:
    """Format a single task for display, showing assignee/category when present."""
    parts: list[str] = []
    if t.assignee or t.category:
        tag_parts = [p for p in (t.assignee, t.category) if p]
        parts.append(f"[{' · '.join(tag_parts)}]")
    parts.append(t.description)
    return f"<b>#{t.id}</b>  {' '.join(parts)}"


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


def _build_task_list_message(
    tasks: list[Task], footer: str = "",
) -> tuple[str, InlineKeyboardMarkup | None]:
    """Build the open-tasks message text and keyboard."""
    if not tasks:
        text = "🎉 All tasks done!"
        if footer:
            text += f"\n\n<i>✔ {footer}</i>"
        return text, None

    lines: list[str] = ["📋 <b>Open Tasks</b>\n"]
    keyboard: list[list[InlineKeyboardButton]] = []
    for t in tasks:
        lines.append(_format_task_line(t))
        keyboard.append(
            [InlineKeyboardButton(f"✅ Done #{t.id}", callback_data=f"task_done:{t.id}")]
        )
    if footer:
        lines.append(f"\n<i>✔ {footer}</i>")
    return "\n".join(lines), InlineKeyboardMarkup(keyboard)


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

    msg_text, keyboard = _build_task_list_message(tasks)
    await update.message.reply_text(
        msg_text,
        parse_mode="HTML",
        reply_markup=keyboard,
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

    msg_text, keyboard = _build_task_list_message(tasks, footer=result)
    try:
        await query.edit_message_text(
            msg_text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    except Exception:
        pass  # message may already be identical


# ── /braindump ──────────────────────────────────────────────────────────


@safe_handler
@whitelist_only
async def braindump_cmd(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """/braindump <text> — bulk-extract tasks from unstructured text via LLM."""
    text = " ".join(context.args) if context.args else ""
    if not text.strip():
        await update.message.reply_text(
            "Usage: /braindump <large block of text with tasks>\n\n"
            "I'll extract individual tasks from it using AI."
        )
        return

    await update.message.reply_text("🧠 Extracting tasks from your braindump…")

    extracted = await extract_tasks(text)
    if not extracted:
        await update.message.reply_text(
            "⚠️ Couldn't extract any tasks from that text. Try rephrasing."
        )
        return

    # Build numbered preview
    lines: list[str] = [f"📋 <b>Braindump Preview</b> ({len(extracted)} tasks)\n"]
    for i, item in enumerate(extracted, 1):
        desc = item.get("description", "(no description)")
        assignee = item.get("assignee")
        category = item.get("category")
        due = item.get("due_date")

        tag_parts = [p for p in (assignee, category) if p]
        tag = f"[{' · '.join(tag_parts)}] " if tag_parts else ""
        due_str = f"  📅 {due}" if due else ""
        lines.append(f"<b>{i}.</b> {tag}{desc}{due_str}")

    # Store extracted tasks in chat_data
    key = f"braindump:{update.message.message_id}"
    context.chat_data[key] = {
        "tasks": extracted,
        "user_id": update.effective_user.id,
        "user_name": update.effective_user.full_name,
    }

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Save all", callback_data=f"bd_save:{key}"),
                InlineKeyboardButton("✏️ Cancel", callback_data=f"bd_cancel:{key}"),
            ]
        ]
    )

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    logger.info("Braindump preview: %d tasks extracted.", len(extracted))


# ── Braindump confirm / cancel callbacks ────────────────────────────────


@safe_handler
async def braindump_save_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle the ✅ Save all button for /braindump."""
    query = update.callback_query
    await query.answer()

    from handlers.security import _allowed_chat_id

    if _allowed_chat_id is not None and query.message.chat.id != _allowed_chat_id:
        return

    key = query.data.split(":", 1)[1]
    data = context.chat_data.pop(key, None)

    if data is None:
        await query.edit_message_text("⚠️ Braindump data expired. Please run /braindump again.")
        return

    extracted = data["tasks"]
    user_id = data["user_id"]
    user_name = data["user_name"]

    created_ids: list[int] = []
    with get_session() as session:
        for item in extracted:
            task = Task(
                description=item.get("description", ""),
                created_by_id=user_id,
                created_by_name=user_name,
                assignee=item.get("assignee"),
                category=item.get("category"),
                due_date=item.get("due_date"),
            )
            session.add(task)
            session.flush()
            created_ids.append(task.id)
        session.commit()

    await query.edit_message_text(
        f"✅ <b>{len(created_ids)} tasks saved!</b>  (IDs: {', '.join(f'#{i}' for i in created_ids)})",
        parse_mode="HTML",
    )
    logger.info("Braindump saved %d tasks by %s.", len(created_ids), user_name)


@safe_handler
async def braindump_cancel_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle the ✏️ Cancel button for /braindump."""
    query = update.callback_query
    await query.answer()

    key = query.data.split(":", 1)[1]
    context.chat_data.pop(key, None)

    await query.edit_message_text("❌ Braindump cancelled — no tasks saved.")
