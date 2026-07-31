from __future__ import annotations

import logging
import asyncio
from pathlib import Path
from collections.abc import Callable, Coroutine
from typing import Any, Tuple

import webhost
from webhost.exceptions import WebHostError

log = logging.getLogger(__name__)


def _make_sync_progress_callback(
    loop: asyncio.AbstractEventLoop,
    async_cb: Callable[[int, int], Coroutine[None, None, None]] | Callable[[int, int], Any] | None,
) -> Callable[[int, int], None] | None:
    if not async_cb:
        return None

    def sync_cb(current: int, total: int) -> None:
        try:
            res = async_cb(current, total)
            if asyncio.iscoroutine(res):
                asyncio.run_coroutine_threadsafe(res, loop)
        except Exception:
            pass

    return sync_cb


from ..user_keys import resolve_upload_api_key

async def upload_to_pixeldrain(
    file_path: Path | str,
    api_key: str | None = None,
    progress_callback: Callable[[int, int], Coroutine[None, None, None]] | None = None,
    domain: str = "pixeldrain.com",
    user_id: int | str | None = None,
) -> Tuple[dict[str, Any], list[str]]:
    """
    Upload a file to Pixeldrain using the webhost package.

    Args:
        file_path: Path to the local file to upload
        api_key: Optional Pixeldrain API Key for authenticated uploads
        progress_callback: Optional async function called with (current_bytes, total_bytes)
        domain: Domain to use for upload API
        user_id: Optional user ID to look up user-specific API keys

    Returns:
        A tuple of (response_json_dict, log_messages_list)
    """
    logs: list[str] = []
    path = Path(file_path)

    if not path.exists():
        logs.append(f"File not found: {path}")
        return {"error": "File not found"}, logs

    api_key = (api_key or resolve_upload_api_key(user_id, "pixeldrain") or "").strip() or None

    logs.append(f"Uploading file: {path.name}")
    if not api_key:
        logs.append("No API key provided, attempting anonymous upload")

    loop = asyncio.get_running_loop()
    sync_cb = _make_sync_progress_callback(loop, progress_callback)

    def _do_upload() -> dict[str, Any]:
        return webhost.pixeldrain.upload_file(
            file_path=str(path),
            api_key=api_key,
            anonymous=not bool(api_key),
            progress_callback=sync_cb
        )

    try:
        res = await asyncio.to_thread(_do_upload)
        logs.append("Uploaded Successfully")
        return res, logs
    except WebHostError as e:
        logs.append(f"Pixeldrain upload failed: {e}")
        return {"error": str(e)}, logs
    except OSError as e:
        logs.append(f"File system error during upload: {e}")
        return {"error": f"File system error: {e}"}, logs
    except Exception as e:
        log.exception("Unexpected error uploading to Pixeldrain")
        logs.append(f"Unexpected error: {e}")
        return {"error": f"Unexpected error: {e}"}, logs
