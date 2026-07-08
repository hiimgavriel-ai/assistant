"""Entrypoint — config validation, service init, handler registration, run_polling."""

import datetime
import logging
import sys
from zoneinfo import ZoneInfo

from telegram import BotCommand
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from config import Config

# ── Logging (stdout for Railway) ────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(name)-24s | %(levelname)-7s | %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


async def post_init(application) -> None:
    """Set the bot's command menu via the Telegram API after startup."""
    await application.bot.set_my_commands(
        [
            BotCommand("add", "Add a task"),
            BotCommand("list", "See all open tasks"),
            BotCommand("braindump", "Bulk-capture tasks from text"),
            BotCommand("note", "Save something to remember"),
            BotCommand("ask", "Ask about history or upcoming events"),
            BotCommand("planevent", "Add a calendar event"),
            BotCommand("agenda", "What's coming up"),
        ]
    )
    logger.info("Bot command menu set via set_my_commands.")


def main() -> None:
    # ── 1. Load & validate config ───────────────────────────────────
    logger.info("Loading configuration…")
    config = Config()
    logger.info("Configuration OK.  Chat whitelist: %s", config.allowed_chat_id)

    # ── 2. Initialise services ──────────────────────────────────────
    from db import init_db

    init_db(config)

    from llm import init_llm

    init_llm(config)

    from gcal import init_gcal

    init_gcal(config)

    from handlers.security import init_security

    init_security(config)

    from handlers.calendar import init_calendar_handlers

    init_calendar_handlers(config)

    from handlers.brain import init_brain

    init_brain(config)

    # ── 3. Build the Application ────────────────────────────────────
    app = (
        Application.builder()
        .token(config.telegram_bot_token)
        .post_init(post_init)
        .build()
    )

    # ── 4. Register handlers ────────────────────────────────────────
    from handlers.security import chatid_cmd, help_cmd, welcome_new_member
    from handlers.tasks import (
        add_cmd,
        braindump_cancel_callback,
        braindump_cmd,
        braindump_save_callback,
        done_cmd,
        list_cmd,
        task_done_callback,
    )
    from handlers.brain import (
        ask_cmd,
        log_message,
        note_cmd,
    )
    from handlers.calendar import (
        agenda_cmd,
        event_cancel_callback,
        event_confirm_callback,
        planevent_cmd,
    )

    # Group 0 — command handlers
    app.add_handler(CommandHandler("chatid", chatid_cmd))
    app.add_handler(CommandHandler("add", add_cmd))
    app.add_handler(CommandHandler("list", list_cmd))
    app.add_handler(CommandHandler("done", done_cmd))
    app.add_handler(CommandHandler("note", note_cmd))
    app.add_handler(CommandHandler("ask", ask_cmd))
    app.add_handler(CommandHandler("planevent", planevent_cmd))
    app.add_handler(CommandHandler("agenda", agenda_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("braindump", braindump_cmd))

    # Inline-button callbacks
    app.add_handler(CallbackQueryHandler(task_done_callback, pattern=r"^task_done:"))
    app.add_handler(CallbackQueryHandler(event_confirm_callback, pattern=r"^evt_create:"))
    app.add_handler(CallbackQueryHandler(event_cancel_callback, pattern=r"^evt_cancel:"))
    app.add_handler(CallbackQueryHandler(braindump_save_callback, pattern=r"^bd_save:"))
    app.add_handler(CallbackQueryHandler(braindump_cancel_callback, pattern=r"^bd_cancel:"))

    # New-member welcome (group 0)
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member))

    # Group 1 — message logger (non-command text only)
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, log_message),
        group=1,
    )

    # ── 5. Schedule daily briefs ────────────────────────────────────
    if config.allowed_chat_id is not None:
        from handlers.briefs import friday_eod, morning_brief

        tz = ZoneInfo(config.timezone)

        # Morning brief every day
        app.job_queue.run_daily(
            morning_brief,
            time=datetime.time(
                hour=config.morning_brief_hour,
                minute=config.morning_brief_minute,
                tzinfo=tz,
            ),
            chat_id=config.allowed_chat_id,
            data={"timezone": config.timezone},
            name="morning_brief",
        )
        logger.info(
            "Morning brief scheduled at %s %s.",
            config.morning_brief_time,
            config.timezone,
        )

        # Friday 17:00 open-task summary
        app.job_queue.run_daily(
            friday_eod,
            time=datetime.time(hour=17, minute=0, tzinfo=tz),
            days=(4,),  # 4 = Friday (Monday=0)
            chat_id=config.allowed_chat_id,
            data={"timezone": config.timezone},
            name="friday_eod",
        )
        logger.info("Friday EOD brief scheduled at 17:00 %s.", config.timezone)
    else:
        logger.warning(
            "Skipping scheduled briefs — ALLOWED_CHAT_ID is not set."
        )

    # ── 6. Start polling ────────────────────────────────────────────
    logger.info("Starting long-polling…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
