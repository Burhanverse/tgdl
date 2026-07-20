from __future__ import annotations

import io
import base64
import json
import logging
import time
import asyncio
from pathlib import Path
from collections.abc import Callable, Coroutine
from typing import Any, Tuple

import aiohttp

log = logging.getLogger(__name__)


class ProgressReader(io.IOBase):
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
                # Update progress if 1 second passed, or 1MB uploaded, or finished
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


async def upload_to_pixeldrain(
    file_path: Path | str,
    api_key: str | None = None,
    progress_callback: Callable[[int, int], Coroutine[None, None, None]] | None = None,
    domain: str = "pixeldrain.com"
) -> Tuple[dict[str, Any], list[str]]:
    """
    Upload a file to Pixeldrain using streaming.

    Args:
        file_path: Path to the local file to upload
        api_key: Optional Pixeldrain API Key for authenticated uploads
        progress_callback: Optional async function called with (current_bytes, total_bytes)
        domain: Domain to use for upload API

    Returns:
        A tuple of (response_json_dict, log_messages_list)
    """
    logs: list[str] = []
    file_path = Path(file_path)

    try:
        if not file_path.exists():
            logs.append(f"File not found: {file_path}")
            return {"error": "File not found"}, logs

        file_size = file_path.stat().st_size
        logs.append(f"Uploading file: {file_path.name}")

        headers = {}
        if api_key:
            credentials = base64.b64encode(f":{api_key}".encode()).decode()
            headers["Authorization"] = f"Basic {credentials}"
        else:
            logs.append("No API key provided, attempting anonymous upload")

        async with aiohttp.ClientSession() as session:
            reader = ProgressReader(file_path, progress_callback)
            try:
                data = aiohttp.FormData()
                data.add_field(
                    "file",
                    reader,
                    filename=file_path.name,
                    content_type="application/octet-stream"
                )

                async with session.post(
                    f"https://{domain}/api/file",
                    data=data,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=None)
                ) as response:
                    if response.status >= 400:
                        error_text = await response.text()
                        logs.append(f"Upload failed with HTTP {response.status}: {error_text}")
                        return {"error": f"HTTP {response.status}: {error_text}"}, logs

                    try:
                        response_data = await response.json(content_type=None)
                    except Exception:
                        text = await response.text()
                        try:
                            response_data = json.loads(text) if text else {"id": None}
                        except Exception:
                            logs.append(f"Could not parse response as JSON: {text[:200]}")
                            response_data = {"id": None, "raw": text}
            finally:
                reader.close()

        logs.append("Uploaded Successfully")
        return response_data, logs

    except aiohttp.ClientError as e:
        logs.append(f"Network error during upload: {e}")
        return {"error": f"Network error: {e}"}, logs
    except OSError as e:
        logs.append(f"File system error during upload: {e}")
        return {"error": f"File system error: {e}"}, logs
    except Exception as e:
        log.exception("Unexpected error uploading to Pixeldrain")
        logs.append(f"Unexpected error: {e}")
        return {"error": f"Unexpected error: {e}"}, logs
