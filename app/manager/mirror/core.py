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
    Uploads a file sequentially to GoFile, FileDitch, and Pixeldrain (skipping Pixeldrain if >10GB).

    Returns:
        Dict mapping host name ("gofile", "fileditch", "pixeldrain") to link or status string.
    """
    file_path = Path(file_path)
    file_size = file_path.stat().st_size if file_path.exists() else 0
    results: Dict[str, str] = {}

    log.info("Starting sequential web host mirroring for %s (size: %s)", file_path.name, format_size(file_size))

    # 1. Upload to GoFile
    try:
        log.info("Uploading %s to GoFile...", file_path.name)
        res_gf, _ = await upload_to_gofile(file_path)
        if isinstance(res_gf, dict) and res_gf.get("status") == "ok":
            link = res_gf.get("data", {}).get("downloadPage")
            if link:
                results["gofile"] = link
            else:
                results["gofile"] = "Failed: Missing download page"
        else:
            err = res_gf.get("error") if isinstance(res_gf, dict) else "Upload failed"
            results["gofile"] = f"Failed: {err}"
    except Exception as e:
        log.warning("GoFile upload error for %s: %s", file_path.name, e)
        results["gofile"] = f"Error: {e}"

    # 2. Upload to FileDitch
    try:
        log.info("Uploading %s to FileDitch...", file_path.name)
        res_fd, _ = await upload_to_fileditch(file_path)
        if isinstance(res_fd, dict) and res_fd.get("success") is True:
            url = res_fd.get("url")
            if url:
                results["fileditch"] = url
            else:
                results["fileditch"] = "Failed: Missing URL"
        else:
            err = res_fd.get("error") if isinstance(res_fd, dict) else "Upload failed"
            results["fileditch"] = f"Failed: {err}"
    except Exception as e:
        log.warning("FileDitch upload error for %s: %s", file_path.name, e)
        results["fileditch"] = f"Error: {e}"

    # 3. Upload to Pixeldrain (skip if > 10GB)
    if file_size > TEN_GB_BYTES:
        log.info("Skipping Pixeldrain for %s: file size %s exceeds 10GB limit", file_path.name, format_size(file_size))
        results["pixeldrain"] = "Skipped (File > 10GB)"
    else:
        try:
            log.info("Uploading %s to Pixeldrain...", file_path.name)
            domain = settings.pixeldrain_domain or "pixeldrain.com"
            res_pd, _ = await upload_to_pixeldrain(
                file_path,
                api_key=settings.pixeldrain_api_key,
                domain=domain
            )
            if isinstance(res_pd, dict) and res_pd.get("id"):
                pd_url = f"https://{domain}/u/{res_pd['id']}"
                results["pixeldrain"] = pd_url
            else:
                err = res_pd.get("error") if isinstance(res_pd, dict) else "Upload failed"
                results["pixeldrain"] = f"Failed: {err}"
        except Exception as e:
            log.warning("Pixeldrain upload error for %s: %s", file_path.name, e)
            results["pixeldrain"] = f"Error: {e}"

    return results
