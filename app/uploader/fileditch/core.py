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

FILEDITCH_PERMANENT_URL = "https://new.fileditch.com/upload.php"
FILEDITCH_TEMP_URL = "https://temp.fileditch.com/upload.php"


class FileDitchProgressReader(io.IOBase):
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


async def upload_to_fileditch(
    file_path: Path | str,
    is_temp: bool = False,
    progress_callback: Callable[[int, int], Coroutine[None, None, None]] | None = None,
) -> Tuple[Dict[str, Any], List[str]]:
    """
    Upload a single file to FileDitch.

    Args:
        file_path: Path to the local file to upload
        is_temp: If True, uploads to temp.fileditch.com (72h retention). Otherwise, new.fileditch.com.
        progress_callback: Optional async function called with (current_bytes, total_bytes)

    Returns:
        A tuple of (response_json_dict, log_messages_list)
    """
    logs: List[str] = []
    file_path = Path(file_path)

    if not file_path.exists():
        logs.append(f"File not found: {file_path}")
        return {"error": "File not found"}, logs

    upload_endpoint = FILEDITCH_TEMP_URL if is_temp else FILEDITCH_PERMANENT_URL
    logs.append(f"Uploading file to FileDitch ({'temp' if is_temp else 'permanent'}): {file_path.name}")

    try:
        async with aiohttp.ClientSession() as session:
            reader = FileDitchProgressReader(file_path, progress_callback)
            try:
                data = aiohttp.FormData()
                data.add_field(
                    "file",
                    reader,
                    filename=file_path.name,
                    content_type="application/octet-stream"
                )

                async with session.post(
                    upload_endpoint,
                    data=data,
                    timeout=aiohttp.ClientTimeout(total=None)
                ) as response:
                    if response.status >= 400:
                        error_text = await response.text()
                        logs.append(f"FileDitch upload failed with HTTP {response.status}: {error_text}")
                        return {"error": f"HTTP {response.status}: {error_text}"}, logs

                    try:
                        response_data = await response.json()
                    except Exception:
                        text = await response.text()
                        try:
                            response_data = json.loads(text) if text else {"success": False}
                        except Exception:
                            logs.append(f"Could not parse FileDitch response as JSON: {text[:200]}")
                            response_data = {"success": False, "raw": text}
            finally:
                reader.close()

        if response_data.get("success") is True:
            logs.append(f"Uploaded to FileDitch successfully: {response_data.get('url')}")
        else:
            logs.append(f"FileDitch API returned error status: {response_data}")

        return response_data, logs

    except Exception as e:
        log.exception("Unexpected error uploading to FileDitch")
        logs.append(f"Unexpected error: {e}")
        return {"error": str(e)}, logs


class FileDitchUploader:
    """Stateful FileDitch uploader supporting directory and single file uploads."""

    def __init__(
        self,
        path: Path,
        is_temp: bool = False,
        progress_callback: Optional[Callable[[int, int], Coroutine[None, None, None]]] = None,
    ) -> None:
        self.path = path
        self.is_temp = is_temp
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
        """Uploads files in self.path to FileDitch and returns (file_urls, summary_dict)."""
        files: List[Path] = []
        if self.path.is_file():
            files.append(self.path)
        else:
            for p in sorted(self.path.rglob("*")):
                if p.is_file() and not p.name.startswith("."):
                    files.append(p)

        if not files:
            return [], {"error": "No files found to upload"}

        file_urls: List[str] = []
        uploaded_count = 0
        failed_count = 0

        for f in files:
            if self.is_cancelled:
                break
            res, _ = await upload_to_fileditch(f, self.is_temp, self.progress_callback)
            if res.get("success") is True:
                url = res.get("url")
                if url:
                    file_urls.append(url)
                uploaded_count += 1
            else:
                failed_count += 1

        summary = {
            "uploaded": uploaded_count,
            "failed": failed_count,
            "total": len(files),
            "urls": file_urls,
        }
        return file_urls, summary

    def cancel_task(self) -> None:
        self.is_cancelled = True
