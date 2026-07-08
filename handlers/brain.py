"""Second-brain handlers — message logging, /note, /decision, /ask."""

import logging
import re

from sqlalchemy import or_, select
from telegram import Update
from telegram.ext import ContextTypes

from db import get_session
from handlers import safe_handler
from handlers.security import whitelist_only
from llm import answer_question
from models import MessageLog, Note, NoteKind

logger = logging.getLogger(__name__)

# Common English stop words to exclude from keyword search
_STOP_WORDS: set[str] = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "must", "can", "could", "about", "above",
    "after", "again", "all", "also", "am", "and", "any", "at", "because",
    "before", "between", "both", "but", "by", "came", "come", "could",
    "each", "for", "from", "get", "got", "he", "her", "here", "him",
    "his", "how", "i", "if", "in", "into", "it", "its", "just", "know",
    "let", "like", "make", "many", "me", "more", "most", "much", "my",
    "no", "not", "now", "of", "on", "one", "only", "or", "other", "our",
    "out", "over", "said", "she", "so", "some", "still", "such", "take",
    "than", "that", "them", "then", "there", "these", "they", "this",
    "those", "through", "to", "too", "under", "up", "us", "very", "want",
    "was", "way", "we", "well", "went", "what", "when", "where", "which",
    "while", "who", "whom", "why", "with", "without", "won", "you", "your",
}


# ── Message logging (runs in handler group 1) ───────────────────────────


@safe_handler
@whitelist_only
async def log_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log every non-command text message in the allowed group."""
    msg = update.effective_message
    if msg is None or not msg.text:
        return

    user = update.effective_user
    with get_session() as session:
        session.add(
            MessageLog(
                tg_message_id=msg.message_id,
                chat_id=msg.chat.id,
                user_id=user.id,
                user_name=user.full_name,
                text=msg.text,
            )
        )
        session.commit()


# ── /note and /decision ──────────────────────────────────────────────────


@safe_handler
@whitelist_only
async def note_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/note <text> — save a high-signal note."""
    text = " ".join(context.args) if context.args else ""
    if not text.strip():
        await update.message.reply_text("Usage: /note <text>")
        return

    _save_note(NoteKind.note, text.strip(), update.effective_user.full_name)
    await update.message.reply_text("📝 Note saved.")
    logger.info("Note saved by %s.", update.effective_user.full_name)


@safe_handler
@whitelist_only
async def decision_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/decision <text> — save a decision."""
    text = " ".join(context.args) if context.args else ""
    if not text.strip():
        await update.message.reply_text("Usage: /decision <text>")
        return

    _save_note(NoteKind.decision, text.strip(), update.effective_user.full_name)
    await update.message.reply_text("⚖️ Decision recorded.")
    logger.info("Decision saved by %s.", update.effective_user.full_name)


def _save_note(kind: NoteKind, content: str, created_by_name: str) -> None:
    with get_session() as session:
        session.add(
            Note(kind=kind, content=content, created_by_name=created_by_name)
        )
        session.commit()


# ── /ask ─────────────────────────────────────────────────────────────────


@safe_handler
@whitelist_only
async def ask_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/ask <question> — answer a question using stored history and notes."""
    question = " ".join(context.args) if context.args else ""
    if not question.strip():
        await update.message.reply_text("Usage: /ask <question>")
        return

    await update.message.reply_text("🤔 Thinking…")

    ctx = _build_context(question)
    answer = await answer_question(ctx, question)
    await update.message.reply_text(answer)


def _build_context(question: str) -> str:
    """Build the retrieval context: recent messages + keyword matches + all notes."""
    with get_session() as session:
        # 1) Most recent 400 messages
        recent_stmt = (
            select(MessageLog)
            .order_by(MessageLog.created_at.desc())
            .limit(400)
        )
        recent_msgs = list(session.execute(recent_stmt).scalars())

        # 2) Keyword-matched messages (ILIKE)
        keywords = _extract_keywords(question)
        keyword_msgs: list[MessageLog] = []
        if keywords:
            conditions = [MessageLog.text.ilike(f"%{kw}%") for kw in keywords]
            kw_stmt = (
                select(MessageLog)
                .where(or_(*conditions))
                .order_by(MessageLog.created_at.desc())
                .limit(200)
            )
            keyword_msgs = list(session.execute(kw_stmt).scalars())

        # 3) All notes
        all_notes = list(
            session.execute(
                select(Note).order_by(Note.created_at)
            ).scalars()
        )

    # De-duplicate messages by id, then sort chronologically
    seen: set[int] = set()
    all_msgs: list[MessageLog] = []
    for m in recent_msgs + keyword_msgs:
        if m.id not in seen:
            seen.add(m.id)
            all_msgs.append(m)
    all_msgs.sort(key=lambda m: m.created_at)

    # Format
    parts: list[str] = []
    if all_msgs:
        parts.append("### Chat History\n")
        for m in all_msgs:
            ts = m.created_at.strftime("%Y-%m-%d %H:%M") if m.created_at else ""
            parts.append(f"[{ts}] {m.user_name}: {m.text}")

    if all_notes:
        parts.append("\n### Notes & Decisions\n")
        for n in all_notes:
            ts = n.created_at.strftime("%Y-%m-%d %H:%M") if n.created_at else ""
            label = "📝 Note" if n.kind == NoteKind.note else "⚖️ Decision"
            parts.append(f"[{ts}] {label} by {n.created_by_name}: {n.content}")

    return "\n".join(parts) if parts else "(No stored context yet.)"


def _extract_keywords(question: str) -> list[str]:
    """Extract significant words from a question for ILIKE search."""
    words = re.findall(r"[a-zA-Z0-9]+", question.lower())
    return [w for w in words if len(w) >= 3 and w not in _STOP_WORDS]
