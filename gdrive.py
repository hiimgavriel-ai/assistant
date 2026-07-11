"""Google Drive integration — folder creation and file uploads."""

import logging

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload

from config import Config

logger = logging.getLogger(__name__)

_service = None


def init_gdrive(config: Config) -> None:
    """Build the Drive API service using service-account credentials."""
    global _service

    credentials = service_account.Credentials.from_service_account_info(
        config.google_service_account_info,
        scopes=[
            "https://www.googleapis.com/auth/calendar.events",
            "https://www.googleapis.com/auth/drive.file",
        ],
    )
    _service = build("drive", "v3", credentials=credentials)
    logger.info("Google Drive client initialised.")


def create_folder(name: str, parent_id: str) -> tuple[str, str]:
    """Create a subfolder inside *parent_id*.

    Returns (folder_id, web_view_link).
    """
    if _service is None:
        raise RuntimeError("Google Drive not initialised.  Call init_gdrive() first.")

    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    folder = (
        _service.files()
        .create(body=metadata, fields="id, webViewLink", supportsAllDrives=True)
        .execute()
    )
    logger.info("Created Drive folder '%s' (id=%s).", name, folder["id"])
    return folder["id"], folder["webViewLink"]


def upload_file(
    file_bytes: bytes,
    filename: str,
    folder_id: str,
    mime_type: str = "image/jpeg",
) -> str:
    """Upload a file into *folder_id*.  Returns the file ID."""
    if _service is None:
        raise RuntimeError("Google Drive not initialised.  Call init_gdrive() first.")

    metadata = {
        "name": filename,
        "parents": [folder_id],
    }
    media = MediaInMemoryUpload(file_bytes, mimetype=mime_type)
    result = (
        _service.files()
        .create(body=metadata, media_body=media, fields="id", supportsAllDrives=True)
        .execute()
    )
    logger.info("Uploaded '%s' to folder %s (file_id=%s).", filename, folder_id, result["id"])
    return result["id"]
