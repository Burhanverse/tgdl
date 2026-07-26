from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple

from ...config import settings
from ...uploader import upload_to_gofile, upload_to_pixeldrain, upload_to_fileditch
from ..status import format_size, make_progress_bar

log = logging.getLogger(__name__)

TEN_GB_BYTES = 10 * 1024 * 1024 * 1024


def compile_mirror_status_text(
    file_name: str,
    file_size_str: str,
    hosts_info: Dict[str, Dict[str, Any]]
) -> str:
    lines = [
        f"**Mirroring Active**",
        f"**File**: `{file_name}` ({file_size_str})",
        "\n"
    ]
    host_labels = [
        ("gofile", "GoFile", "🟢"),
        ("fileditch", "FileDitch", "🔵"),
        ("pixeldrain", "Pixeldrain", "🟣")
    ]

    for idx, (key, label, icon) in enumerate(host_labels):
        tree = "├" if idx < len(host_labels) - 1 else "└"
        info = hosts_info.get(key, {})
        st = info.get("status", "pending")
        if st == "pending":
            lines.append(f"{tree} {icon} **{label}**: `Pending`")
        elif st == "uploading":
            pct = info.get("pct", 0.0)
            spd = info.get("speed", 0.0)
            bar = make_progress_bar(pct)
            spd_str = f"{format_size(spd)}/s" if spd > 0 else "0 B/s"
            lines.append(f"{tree} {icon} **{label}**: `{bar}` {pct:.1f}% ({spd_str})")
        elif st == "done":
            url = info.get("url")
            if url:
                lines.append(f"{tree} {icon} **[{label}]({url})**: `Uploaded`")
            else:
                lines.append(f"{tree} {icon} **{label}**: `Uploaded`")
        elif st == "skipped":
            lines.append(f"{tree} {icon} **{label}**: `Skipped (>10GB)`")
        elif st == "failed":
            err = info.get("error", "Failed")
            lines.append(f"{tree} {icon} **{label}**: `{err}`")

    return "\n".join(lines)


async def mirror_file_to_web_hosts(
    file_path: Path,
    status_callback: Optional[Callable[[str], Coroutine[None, None, None]]] = None
) -> Dict[str, str]:
    """
    Uploads a file sequentially to GoFile, FileDitch, and Pixeldrain with dynamic status updates.

    Returns:
        Dict mapping host name ("gofile", "fileditch", "pixeldrain") to link or status string.
    """
    file_path = Path(file_path)
    file_size = file_path.stat().st_size if file_path.exists() else 0
    file_size_str = format_size(file_size)
    results: Dict[str, str] = {}

    hosts_info: Dict[str, Dict[str, Any]] = {
        "gofile": {"status": "pending"},
        "fileditch": {"status": "pending"},
        "pixeldrain": {"status": "skipped" if file_size > TEN_GB_BYTES else "pending"}
    }

    log.info("Starting sequential web host mirroring for %s (size: %s)", file_path.name, file_size_str)

    async def notify_update() -> None:
        if status_callback:
            txt = compile_mirror_status_text(file_path.name, file_size_str, hosts_info)
            try:
                await status_callback(txt)
            except Exception:
                pass

    # 1. Upload to GoFile
    hosts_info["gofile"]["status"] = "uploading"
    await notify_update()

    start_gf = time.time()
    last_gf_t = start_gf
    last_gf_b = 0

    async def on_gofile_progress(current: int, total: int) -> None:
        nonlocal last_gf_t, last_gf_b
        now = time.time()
        elapsed = now - last_gf_t
        speed = 0.0
        if elapsed >= 1.0:
            speed = (current - last_gf_b) / elapsed
            last_gf_t = now
            last_gf_b = current
        pct = (current / total * 100.0) if total > 0 else 0.0
        hosts_info["gofile"].update({"status": "uploading", "pct": pct, "speed": speed})
        await notify_update()

    try:
        log.info("Uploading %s to GoFile...", file_path.name)
        res_gf, _ = await upload_to_gofile(file_path, progress_callback=on_gofile_progress)
        if isinstance(res_gf, dict) and res_gf.get("status") == "ok":
            link = res_gf.get("data", {}).get("downloadPage")
            if link:
                results["gofile"] = link
                hosts_info["gofile"] = {"status": "done", "link": link}
            else:
                results["gofile"] = "Failed: Missing download page"
                hosts_info["gofile"] = {"status": "failed", "error": "Missing download page"}
        else:
            err = res_gf.get("error") if isinstance(res_gf, dict) else "Upload failed"
            results["gofile"] = f"Failed: {err}"
            hosts_info["gofile"] = {"status": "failed", "error": str(err)}
    except Exception as e:
        log.warning("GoFile upload error for %s: %s", file_path.name, e)
        results["gofile"] = f"Error: {e}"
        hosts_info["gofile"] = {"status": "failed", "error": str(e)}

    await notify_update()

    # 2. Upload to FileDitch
    hosts_info["fileditch"]["status"] = "uploading"
    await notify_update()

    start_fd = time.time()
    last_fd_t = start_fd
    last_fd_b = 0

    async def on_fileditch_progress(current: int, total: int) -> None:
        nonlocal last_fd_t, last_fd_b
        now = time.time()
        elapsed = now - last_fd_t
        speed = 0.0
        if elapsed >= 1.0:
            speed = (current - last_fd_b) / elapsed
            last_fd_t = now
            last_fd_b = current
        pct = (current / total * 100.0) if total > 0 else 0.0
        hosts_info["fileditch"].update({"status": "uploading", "pct": pct, "speed": speed})
        await notify_update()

    try:
        log.info("Uploading %s to FileDitch...", file_path.name)
        res_fd, _ = await upload_to_fileditch(file_path, progress_callback=on_fileditch_progress)
        if isinstance(res_fd, dict) and res_fd.get("success") is True:
            url = res_fd.get("url")
            if url:
                results["fileditch"] = url
                hosts_info["fileditch"] = {"status": "done", "link": url}
            else:
                results["fileditch"] = "Failed: Missing URL"
                hosts_info["fileditch"] = {"status": "failed", "error": "Missing URL"}
        else:
            err = res_fd.get("error") if isinstance(res_fd, dict) else "Upload failed"
            results["fileditch"] = f"Failed: {err}"
            hosts_info["fileditch"] = {"status": "failed", "error": str(err)}
    except Exception as e:
        log.warning("FileDitch upload error for %s: %s", file_path.name, e)
        results["fileditch"] = f"Error: {e}"
        hosts_info["fileditch"] = {"status": "failed", "error": str(e)}

    await notify_update()

    # 3. Upload to Pixeldrain (skip if > 10GB)
    if file_size > TEN_GB_BYTES:
        log.info("Skipping Pixeldrain for %s: file size %s exceeds 10GB limit", file_path.name, file_size_str)
        results["pixeldrain"] = "Skipped (File > 10GB)"
        hosts_info["pixeldrain"] = {"status": "skipped"}
    else:
        hosts_info["pixeldrain"]["status"] = "uploading"
        await notify_update()

        start_pd = time.time()
        last_pd_t = start_pd
        last_pd_b = 0

        async def on_pixeldrain_progress(current: int, total: int) -> None:
            nonlocal last_pd_t, last_pd_b
            now = time.time()
            elapsed = now - last_pd_t
            speed = 0.0
            if elapsed >= 1.0:
                speed = (current - last_pd_b) / elapsed
                last_pd_t = now
                last_pd_b = current
            pct = (current / total * 100.0) if total > 0 else 0.0
            hosts_info["pixeldrain"].update({"status": "uploading", "pct": pct, "speed": speed})
            await notify_update()

        try:
            log.info("Uploading %s to Pixeldrain...", file_path.name)
            domain = settings.pixeldrain_domain or "pixeldrain.com"
            res_pd, _ = await upload_to_pixeldrain(
                file_path,
                api_key=settings.pixeldrain_api_key,
                domain=domain,
                progress_callback=on_pixeldrain_progress
            )
            if isinstance(res_pd, dict) and res_pd.get("id"):
                pd_url = f"https://{domain}/u/{res_pd['id']}"
                results["pixeldrain"] = pd_url
                hosts_info["pixeldrain"] = {"status": "done", "link": pd_url}
            else:
                err = res_pd.get("error") if isinstance(res_pd, dict) else "Upload failed"
                results["pixeldrain"] = f"Failed: {err}"
                hosts_info["pixeldrain"] = {"status": "failed", "error": str(err)}
        except Exception as e:
            log.warning("Pixeldrain upload error for %s: %s", file_path.name, e)
            results["pixeldrain"] = f"Error: {e}"
            hosts_info["pixeldrain"] = {"status": "failed", "error": str(e)}

    await notify_update()
    return results
