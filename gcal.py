"""Google Calendar integration (service-account auth)."""

import logging
from datetime import datetime

from google.oauth2 import service_account
from googleapiclient.discovery import build

from config import Config

logger = logging.getLogger(__name__)

_service = None
_calendar_id: str = ""
_timezone: str = ""


def init_gcal(config: Config) -> None:
    """Build the Calendar API service using service-account credentials."""
    global _service, _calendar_id, _timezone

    credentials = service_account.Credentials.from_service_account_info(
        config.google_service_account_info,
        scopes=[
            "https://www.googleapis.com/auth/calendar.events",
            "https://www.googleapis.com/auth/drive.file",
        ],
    )
    _service = build("calendar", "v3", credentials=credentials)
    _calendar_id = config.google_calendar_id
    _timezone = config.timezone
    logger.info("Google Calendar client initialised (calendar=%s).", _calendar_id)


def create_event(
    title: str,
    start_iso: str,
    end_iso: str,
    location: str = "",
) -> dict:
    """Insert an event on the configured calendar.  Returns the created event."""
    if _service is None:
        raise RuntimeError("Google Calendar not initialised.  Call init_gcal() first.")

    body: dict = {
        "summary": title,
        "start": {"dateTime": start_iso, "timeZone": _timezone},
        "end": {"dateTime": end_iso, "timeZone": _timezone},
    }
    if location:
        body["location"] = location

    event = _service.events().insert(calendarId=_calendar_id, body=body).execute()
    logger.info("Created event '%s' (id=%s).", title, event.get("id"))
    return event


def list_events(time_min: datetime, time_max: datetime) -> list[dict]:
    """Return events between *time_min* and *time_max* (both tz-aware)."""
    if _service is None:
        raise RuntimeError("Google Calendar not initialised.  Call init_gcal() first.")

    result = (
        _service.events()
        .list(
            calendarId=_calendar_id,
            timeMin=time_min.isoformat(),
            timeMax=time_max.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            timeZone=_timezone,
        )
        .execute()
    )
    return result.get("items", [])
