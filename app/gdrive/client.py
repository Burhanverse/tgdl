from __future__ import annotations

import logging
import re
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

from googleapiclient.errors import HttpError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .auth import GoogleDriveAuthManager

log = logging.getLogger(__name__)

G_DRIVE_DIR_MIME_TYPE = "application/vnd.google-apps.folder"

EXPORT_MAP = {
    "application/vnd.google-apps.document": {
        "mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "ext": ".docx",
    },
    "application/vnd.google-apps.spreadsheet": {
        "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "ext": ".xlsx",
    },
    "application/vnd.google-apps.presentation": {
        "mime": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "ext": ".pptx",
    },
    "application/vnd.google-apps.drawing": {
        "mime": "image/png",
        "ext": ".png",
    },
}


def sanitize_filename(name: str) -> str:
    """Sanitize filename to prevent directory traversal and remove invalid OS filesystem characters."""
    name = re.sub(r'[/\\:*?"<>|]', "_", name).strip()
    return name or "unnamed_file"


def get_id_from_url(url: str) -> str:
    url = url.strip()
    if re.match(r"^[a-zA-Z0-9_-]{25,}$", url):
        return url

    parsed = urlparse(url)
    if "drive.google.com" in parsed.netloc or "docs.google.com" in parsed.netloc:
        path_parts = [p for p in parsed.path.split("/") if p]

        if "d" in path_parts:
            idx = path_parts.index("d")
            if idx + 1 < len(path_parts):
                return path_parts[idx + 1]

        if "folders" in path_parts:
            idx = path_parts.index("folders")
            if idx + 1 < len(path_parts):
                return path_parts[idx + 1]

        qs = parse_qs(parsed.query)
        if "id" in qs:
            return qs["id"][0]

    raise ValueError(f"Could not extract Google Drive ID from link: '{url}'")


class GoogleDriveClient:
    def __init__(
        self,
        auth_manager: Optional[GoogleDriveAuthManager] = None,
        user_id: Optional[int | str] = None,
    ):
        self.auth_manager = auth_manager or GoogleDriveAuthManager(user_id=user_id)
        self._service = None

    @property
    def service(self):
        if self._service is None:
            self._service = self.auth_manager.build_service()
        return self._service

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((HttpError, IOError)),
        reraise=True,
    )
    def get_file_metadata(self, file_id: str) -> dict[str, Any]:
        fields = "id, name, mimeType, size, parents"
        try:
            return (
                self.service.files()
                .get(fileId=file_id, fields=fields, supportsAllDrives=True)
                .execute()
            )
        except HttpError as e:
            if e.resp.status == 404:
                raise FileNotFoundError(f"Google Drive item '{file_id}' not found or inaccessible.") from e
            elif e.resp.status == 403:
                raise PermissionError(f"Permission denied accessing Google Drive item '{file_id}'.") from e
            raise

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((HttpError, IOError)),
        reraise=True,
    )
    def list_folder_contents(self, folder_id: str) -> list[dict[str, Any]]:
        items = []
        page_token = None
        query = f"'{folder_id}' in parents and trashed = false"

        while True:
            response = (
                self.service.files()
                .list(
                    q=query,
                    spaces="drive",
                    fields="nextPageToken, files(id, name, mimeType, size)",
                    pageToken=page_token,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute()
            )
            items.extend(response.get("files", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break

        return items
