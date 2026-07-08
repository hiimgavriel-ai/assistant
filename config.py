"""Load and validate all configuration from environment variables."""

import base64
import json
import os
import sys

from dotenv import load_dotenv

# Load .env for local development only
load_dotenv()


class Config:
    """Immutable configuration loaded from environment variables."""

    def __init__(self) -> None:
        # ── Required variables ──────────────────────────────────────────
        required = [
            "TELEGRAM_BOT_TOKEN",
            "ANTHROPIC_API_KEY",
            "GOOGLE_CALENDAR_ID",
            "GOOGLE_SERVICE_ACCOUNT_B64",
            "DATABASE_URL",
        ]
        missing = [v for v in required if not os.getenv(v)]
        if missing:
            print("❌ Missing required environment variables:", file=sys.stderr)
            for v in missing:
                print(f"   • {v}", file=sys.stderr)
            sys.exit(1)

        self.telegram_bot_token: str = os.environ["TELEGRAM_BOT_TOKEN"]
        self.anthropic_api_key: str = os.environ["ANTHROPIC_API_KEY"]
        self.google_calendar_id: str = os.environ["GOOGLE_CALENDAR_ID"]

        # ── ALLOWED_CHAT_ID (may be unset on first deploy) ──────────────
        raw_chat_id = os.getenv("ALLOWED_CHAT_ID")
        self.allowed_chat_id: int | None = int(raw_chat_id) if raw_chat_id else None
        if self.allowed_chat_id is None:
            print(
                "⚠️  ALLOWED_CHAT_ID is not set. "
                "Bot will only respond to /chatid until it is configured."
            )

        # ── Optional variables with defaults ────────────────────────────
        self.llm_model: str = os.getenv("LLM_MODEL", "claude-sonnet-4-20250514")
        self.timezone: str = os.getenv("TIMEZONE", "Asia/Singapore")
        self.morning_brief_time: str = os.getenv("MORNING_BRIEF_TIME", "08:00")

        # ── Google service-account JSON (base64-encoded) ────────────────
        sa_b64 = os.environ["GOOGLE_SERVICE_ACCOUNT_B64"]
        try:
            self.google_service_account_info: dict = json.loads(
                base64.b64decode(sa_b64)
            )
        except Exception as exc:
            print(
                f"❌ Failed to decode GOOGLE_SERVICE_ACCOUNT_B64: {exc}",
                file=sys.stderr,
            )
            sys.exit(1)

        # ── DATABASE_URL normalisation ──────────────────────────────────
        db_url = os.environ["DATABASE_URL"]
        if db_url.startswith("postgresql://"):
            db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)
        self.database_url: str = db_url

    # Convenience helpers ────────────────────────────────────────────────
    @property
    def morning_brief_hour(self) -> int:
        return int(self.morning_brief_time.split(":")[0])

    @property
    def morning_brief_minute(self) -> int:
        return int(self.morning_brief_time.split(":")[1])
