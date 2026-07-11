"""Photo-dump handlers — /photodump, photo collection, /finish."""

import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes

import gdrive
from config import Config
from handlers import safe_handler
from handlers.security import _allowed_chat_id, whitelist_only

logger = logging.getLogger(__name__)

_parent_folder_id: str | None = None

# ── Chat-data keys for the state machine ────────────────────────────────
_STATE = "photodump_state"
_FOLDER_ID = "photodump_folder_id"
_FOLDER_LINK = "photodump_folder_link"
_EVENT_NAME = "photodump_event_name"
_COUNT = "photodump_count"

# States
_AWAITING_NAME = "awaiting_name"
_COLLECTING = "collecting"


def init_photos(config: Config) -> None:
    """Store the parent Drive folder ID."""
    global _parent_folder_id
    _parent_folder_id = config.gdrive_parent_folder_id
    if _parent_folder_id:
        logger.info("Photodump enabled (parent folder=%s).", _parent_folder_id)
    else:
        logger.warning("GDRIVE_PARENT_FOLDER_ID not set — /photodump disabled.")


# ── /photodump ──────────────────────────────────────────────────────────


@safe_handler
@whitelist_only
async def photodump_cmd(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """/photodump — start a photo collection session."""
    if not _parent_folder_id:
        await update.message.reply_text(
            "⚠️ Photo uploads aren't configured yet.\n"
            "Set <b>GDRIVE_PARENT_FOLDER_ID</b> and redeploy.",
            parse_mode="HTML",
        )
        return

    # If already in a session, let the user know
    if context.chat_data.get(_STATE) == _COLLECTING:
        link = context.chat_data.get(_FOLDER_LINK, "")
        await update.message.reply_text(
            f"📸 A photodump session is already active.\n"
            f"📁 {link}\n\n"
            "Send photos, or /finish to end it.",
        )
        return

    context.chat_data[_STATE] = _AWAITING_NAME
    await update.message.reply_text("📸 What event are these photos for?")


# ── Receive event name (text while awaiting) ────────────────────────────


@safe_handler
async def receive_event_name(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle the next text message as the event name."""
    # Quick bail — completely silent when no photodump session is active
    if context.chat_data.get(_STATE) != _AWAITING_NAME:
        return
    if _allowed_chat_id is not None and update.effective_chat.id != _allowed_chat_id:
        return

    event_name = update.message.text.strip()
    if not event_name:
        return

    await update.message.reply_text(f'📁 Creating folder for "{event_name}"…')

    try:
        folder_id, folder_link = await asyncio.to_thread(
            gdrive.create_folder, event_name, _parent_folder_id
        )
    except Exception as exc:
        logger.exception("Failed to create Drive folder")
        context.chat_data.pop(_STATE, None)
        await update.message.reply_text(f"⚠️ Couldn't create folder: {exc}")
        return

    context.chat_data[_STATE] = _COLLECTING
    context.chat_data[_FOLDER_ID] = folder_id
    context.chat_data[_FOLDER_LINK] = folder_link
    context.chat_data[_EVENT_NAME] = event_name
    context.chat_data[_COUNT] = 0

    await update.message.reply_text(
        f'✅ Folder ready: <a href="{folder_link}">{event_name}</a>\n\n'
        "Send photos now — I'll upload them and clean up the chat.\n"
        "When you're done, send /finish.",
        parse_mode="HTML",
    )


# ── Receive photos (compressed) ────────────────────────────────────────


@safe_handler
async def receive_photo(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Upload a photo to the active Drive folder."""
    # Quick bail — completely silent when no photodump session is active
    if context.chat_data.get(_STATE) != _COLLECTING:
        return
    if _allowed_chat_id is not None and update.effective_chat.id != _allowed_chat_id:
        return

    folder_id = context.chat_data[_FOLDER_ID]

    # Highest resolution is the last PhotoSize in the array
    photo = update.message.photo[-1]
    tg_file = await context.bot.get_file(photo.file_id)
    file_bytes = bytes(await tg_file.download_as_bytearray())

    count = context.chat_data[_COUNT] + 1
    filename = f"photo_{count:03d}.jpg"

    try:
        await asyncio.to_thread(
            gdrive.upload_file, file_bytes, filename, folder_id, "image/jpeg"
        )
        context.chat_data[_COUNT] = count
    except Exception as exc:
        logger.exception("Failed to upload photo to Drive")
        await update.message.reply_text(f"⚠️ Upload failed: {exc}")
        return

    # Delete the photo message from the chat to keep it clean
    try:
        await update.message.delete()
    except Exception:
        logger.warning(
            "Could not delete photo message %s (bot may need admin rights).",
            update.message.message_id,
        )


# ── Receive document images (uncompressed) ──────────────────────────────


@safe_handler
async def receive_document_photo(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Upload a document-type image to the active Drive folder."""
    # Quick bail — completely silent when no photodump session is active
    if context.chat_data.get(_STATE) != _COLLECTING:
        return
    if _allowed_chat_id is not None and update.effective_chat.id != _allowed_chat_id:
        return

    doc = update.message.document
    if not doc or not doc.mime_type or not doc.mime_type.startswith("image/"):
        return  # not an image document

    folder_id = context.chat_data[_FOLDER_ID]

    tg_file = await context.bot.get_file(doc.file_id)
    file_bytes = bytes(await tg_file.download_as_bytearray())

    count = context.chat_data[_COUNT] + 1
    filename = doc.file_name or f"photo_{count:03d}"

    try:
        await asyncio.to_thread(
            gdrive.upload_file, file_bytes, filename, folder_id, doc.mime_type
        )
        context.chat_data[_COUNT] = count
    except Exception as exc:
        logger.exception("Failed to upload document photo to Drive")
        await update.message.reply_text(f"⚠️ Upload failed: {exc}")
        return

    try:
        await update.message.delete()
    except Exception:
        logger.warning(
            "Could not delete document message %s.",
            update.message.message_id,
        )


# ── /finish ─────────────────────────────────────────────────────────────


@safe_handler
@whitelist_only
async def finish_cmd(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """/finish — end the photodump session and report."""
    state = context.chat_data.get(_STATE)
    if state not in (_AWAITING_NAME, _COLLECTING):
        await update.message.reply_text("No active photodump session.")
        return

    count = context.chat_data.get(_COUNT, 0)
    folder_link = context.chat_data.get(_FOLDER_LINK, "")
    event_name = context.chat_data.get(_EVENT_NAME, "")

    # Clear all photodump state
    for key in (_STATE, _FOLDER_ID, _FOLDER_LINK, _EVENT_NAME, _COUNT):
        context.chat_data.pop(key, None)

    if count > 0:
        await update.message.reply_text(
            f'📸 Done! <b>{count}</b> photo(s) uploaded for "{event_name}".\n'
            f'📁 <a href="{folder_link}">Open folder</a>',
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(
            "📸 Photodump ended — no photos were uploaded."
        )
