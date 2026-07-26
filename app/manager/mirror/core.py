from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ...config import settings
from ...uploader import upload_to_gofile, upload_to_pixeldrain, upload_to_fileditch
from ..status import format_size

log = logging.getLogger(__name__)

TEN_GB_BYTES = 10 * 1024 * 1024 * 1024  # 10 GB ceiling for Pixeldrain


async def mirror_file_to_web_hosts(file_path: Path) -> Dict[str, str]:
    """
    Uploads a file in parallel to GoFile, FileDitch, and Pixeldrain (skipping Pixeldrain if >10GB).

    Returns:
        Dict mapping host name ("gofile", "fileditch", "pixeldrain") to link or status string.
    """
    file_path = Path(file_path)
    file_size = file_path.stat().st_size if file_path.exists() else 0
    results: Dict[str, str] = {}

    log.info("Starting parallel web host mirroring for %s (size: %s)", file_path.name, format_size(file_size))

    # 1. Prepare GoFile upload task
    async def task_gofile() -> Tuple[str, str]:
        try:
            res, _ = await upload_to_gofile(file_path)
            if isinstance(res, dict) and res.get("status") == "ok":
                link = res.get("data", {}).get("downloadPage")
                if link:
                    return "gofile", link
            err = res.get("error") if isinstance(res, dict) else "Upload failed"
            return "gofile", f"Failed: {err}"
        except Exception as e:
            log.warning("Parallel GoFile upload error for %s: %s", file_path.name, e)
            return "gofile", f"Error: {e}"

    # 2. Prepare FileDitch upload task
    async def task_fileditch() -> Tuple[str, str]:
        try:
            res, _ = await upload_to_fileditch(file_path)
            if isinstance(res, dict) and res.get("success") is True:
                url = res.get("url")
                if url:
                    return "fileditch", url
            err = res.get("error") if isinstance(res, dict) else "Upload failed"
            return "fileditch", f"Failed: {err}"
        except Exception as e:
            log.warning("Parallel FileDitch upload error for %s: %s", file_path.name, e)
            return "fileditch", f"Error: {e}"

    # 3. Prepare Pixeldrain upload task (skip if > 10GB)
    async def task_pixeldrain() -> Tuple[str, str]:
        if file_size > TEN_GB_BYTES:
            log.info("Skipping Pixeldrain for %s: file size %s exceeds 10GB limit", file_path.name, format_size(file_size))
            return "pixeldrain", "Skipped (File > 10GB)"

        try:
            domain = settings.pixeldrain_domain or "pixeldrain.com"
            res, _ = await upload_to_pixeldrain(
                file_path,
                api_key=settings.pixeldrain_api_key,
                domain=domain
            )
            if isinstance(res, dict) and res.get("id"):
                pd_url = f"https://{domain}/u/{res['id']}"
                return "pixeldrain", pd_url
            err = res.get("error") if isinstance(res, dict) else "Upload failed"
            return "pixeldrain", f"Failed: {err}"
        except Exception as e:
            log.warning("Parallel Pixeldrain upload error for %s: %s", file_path.name, e)
            return "pixeldrain", f"Error: {e}"

    # Execute all 3 host upload tasks in PARALLEL via asyncio.gather
    host_results = await asyncio.gather(
        task_gofile(),
        task_fileditch(),
        task_pixeldrain(),
        return_exceptions=True
    )

    for item in host_results:
        if isinstance(item, tuple) and len(item) == 2:
            host_name, status_str = item
            results[host_name] = status_str

    return results
