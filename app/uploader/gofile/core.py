from __future__ import annotations

import io
import json
import logging
import time
import asyncio
from pathlib import Path
from collections.abc import Callable, Coroutine
from typing import Any, Dict, List, Optional, Tuple, Union

import aiohttp

from ...config import settings

log = logging.getLogger(__name__)

GOFILE_SERVERS_URL = "https://api.gofile.io/servers"
_UPLOAD_CHUNK = 1024 * 1024


class GoFileProgressReader(io.IOBase):
    """
    A file-like object wrapper that reports read progress to an async callback.
    """
    def __init__(
        self, 
        file_path: Path, 
        callback: Callable[[int, int], Coroutine[None, None, None]] | None = None
    ):
        super().__init__()
        self.file_path = file_path
        self.total_size = file_path.stat().st_size
        self.callback = callback
        self.read_bytes = 0
        self.file = open(file_path, "rb")
        self.last_update_time = 0.0
        self.last_update_bytes = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self.file.read(size)
        if chunk:
            self.read_bytes += len(chunk)
            if self.callback:
                now = time.time()
                if (
                    now - self.last_update_time >= 1.0 
                    or self.read_bytes - self.last_update_bytes >= 1024 * 1024 
                    or self.read_bytes == self.total_size
                ):
                    self.last_update_time = now
                    self.last_update_bytes = self.read_bytes
                    try:
                        loop = asyncio.get_running_loop()
                        if loop.is_running():
                            loop.create_task(self.callback(self.read_bytes, self.total_size))
                    except RuntimeError:
                        pass
        return chunk

    def close(self) -> None:
        self.file.close()
        super().close()

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return False

    def __len__(self) -> int:
        return self.total_size


async def get_gofile_server(session: aiohttp.ClientSession) -> str:
    """Queries GoFile API to retrieve the best available upload server."""
    async with session.get(GOFILE_SERVERS_URL) as resp:
        if resp.status != 200:
            text = await resp.text()
            raise RuntimeError(f"GoFile server lookup failed [{resp.status}]: {text[:200]}")
        payload = await resp.json()
        if payload.get("status") != "ok":
            raise RuntimeError(f"GoFile server lookup failed: {payload}")
        servers = payload.get("data", {}).get("servers", [])
        if not servers:
            raise RuntimeError("GoFile server lookup returned no servers")
        server_name = servers[0].get("name")
        if not server_name:
            raise RuntimeError("GoFile server response missing server name")
        return f"https://{server_name}.gofile.io/contents/uploadfile"


async def upload_to_gofile(
    file_path: Path | str,
    api_token: str | None = None,
    progress_callback: Callable[[int, int], Coroutine[None, None, None]] | None = None,
) -> Tuple[Dict[str, Any], List[str]]:
    """
    Upload a single file to GoFile.

    Args:
        file_path: Path to the local file to upload
        api_token: Optional GoFile API Token for authenticated uploads
        progress_callback: Optional async function called with (current_bytes, total_bytes)

    Returns:
        A tuple of (response_json_dict, log_messages_list)
    """
    logs: List[str] = []
    file_path = Path(file_path)

    if not file_path.exists():
        logs.append(f"File not found: {file_path}")
        return {"error": "File not found"}, logs

    token = (api_token or getattr(settings, "gofile_api_key", None) or "").strip()
    logs.append(f"Uploading file to GoFile: {file_path.name}")

    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        async with aiohttp.ClientSession() as session:
            upload_url = await get_gofile_server(session)
            reader = GoFileProgressReader(file_path, progress_callback)
            try:
                data = aiohttp.FormData()
                if token:
                    data.add_field("token", token)
                data.add_field(
                    "file",
                    reader,
                    filename=file_path.name,
                    content_type="application/octet-stream"
                )

                async with session.post(
                    upload_url,
                    data=data,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=None)
                ) as response:
                    if response.status >= 400:
                        error_text = await response.text()
                        logs.append(f"GoFile upload failed with HTTP {response.status}: {error_text}")
                        return {"error": f"HTTP {response.status}: {error_text}"}, logs

                    try:
                        response_data = await response.json()
                    except Exception:
                        text = await response.text()
                        try:
                            response_data = json.loads(text) if text else {"status": "error"}
                        except Exception:
                            logs.append(f"Could not parse GoFile response as JSON: {text[:200]}")
                            response_data = {"status": "error", "raw": text}
            finally:
                reader.close()

        if response_data.get("status") == "ok":
            logs.append("Uploaded to GoFile successfully")
        else:
            logs.append(f"GoFile API returned error status: {response_data}")

        return response_data, logs

    except Exception as e:
        log.exception("Unexpected error uploading to GoFile")
        logs.append(f"Unexpected error: {e}")
        return {"error": str(e)}, logs


class GoFileUploader:
    """Stateful GoFile uploader supporting directory and single file uploads."""

    def __init__(
        self,
        path: Path,
        api_token: Optional[str] = None,
        progress_callback: Optional[Callable[[int, int], Coroutine[None, None, None]]] = None,
    ) -> None:
        self.path = path
        self.api_token = api_token or getattr(settings, "gofile_api_key", None)
        self.progress_callback = progress_callback
        self.processed_bytes = 0
        self.start_time = time.time()
        self.is_cancelled = False

    @property
    def speed(self) -> float:
        elapsed = time.time() - self.start_time
        if elapsed > 0:
            return self.processed_bytes / elapsed
        return 0.0

    async def upload(self) -> Tuple[List[str], Dict[str, Any]]:
        """Uploads files in self.path to GoFile and returns (page_links, summary_dict)."""
        files: List[Path] = []
        if self.path.is_file():
            files.append(self.path)
        else:
            for p in sorted(self.path.rglob("*")):
                if p.is_file() and not p.name.startswith("."):
                    files.append(p)

        if not files:
            return [], {"error": "No files found to upload"}

        page_links: List[str] = []
        uploaded_count = 0
        failed_count = 0

        for f in files:
            if self.is_cancelled:
                break
            res, _ = await upload_to_gofile(f, self.api_token, self.progress_callback)
            if res.get("status") == "ok":
                data = res.get("data", {})
                link = data.get("downloadPage")
                if link:
                    page_links.append(link)
                uploaded_count += 1
            else:
                failed_count += 1

        summary = {
            "uploaded": uploaded_count,
            "failed": failed_count,
            "total": len(files),
            "links": page_links,
        }
        return page_links, summary

    def cancel_task(self) -> None:
        self.is_cancelled = True
