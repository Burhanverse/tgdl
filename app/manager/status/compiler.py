from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ...db import Job
    from ..state import JobState

from .messaging import format_size, make_progress_bar

def make_marquee_bar(width: int = 10) -> str:
    import time
    pos = int(time.time() * 2) % (width * 2 - 2)
    if pos >= width:
        pos = (width * 2 - 2) - pos
    bar = ["░"] * width
    bar[pos] = "█"
    return "".join(bar)

def format_url_display(url_json: str) -> str:
    try:
        urls = json.loads(url_json)
        if isinstance(urls, list):
            if len(urls) == 1:
                return f"`{urls[0]}`"
            return f"`{urls[0]}` (+ {len(urls) - 1} more)"
    except Exception:
        pass
    return f"`{url_json}`"


def compile_split_prompt_text(job_id: str, url_or_target: str, is_torrent: bool = False, is_unzip: bool = False) -> str:
    if is_torrent:
        title = f"**Torrent Job #{job_id} Registered**"
        target_label = "Target"
    elif is_unzip:
        title = f"**Job #{job_id} Registered**"
        target_label = "Archive"
    else:
        title = f"**Job #{job_id} Registered**"
        target_label = "URL"
    
    display = format_url_display(url_or_target) if not (is_torrent or is_unzip) else url_or_target
    return (
        f"{title}\n"
        f"------------------------------------\n"
        f"- **{target_label}**: {display}\n\n"
        "Do you want to split files larger than 2GB for this job?"
    )


def compile_queued_status_text(job_id: str, url: str, args_display: str) -> str:
    cleaned_url = url
    if url.startswith("[") and url.endswith("]"):
        try:
            import json
            parsed = json.loads(url)
            if parsed and isinstance(parsed, list):
                cleaned_url = parsed[0]
        except Exception:
            pass

    is_torrent = (
        cleaned_url.startswith("magnet:") or
        cleaned_url.startswith("torrent:") or
        cleaned_url.endswith(".torrent") or
        "magnet:?xt=" in cleaned_url
    )
    if is_torrent:
        if cleaned_url.startswith("torrent:"):
            torrent_path = cleaned_url[len("torrent:"):]
            name = Path(torrent_path).name
            return (
                f"**Task Queued** • `#job_{job_id}`\n"
                f"\n\n"
                f"• **Torrent**: `{name}`\n"
                f"• **Engine**: `aria2c`"
            )
        else:
            magnet_disp = cleaned_url[:55] + "..." if len(cleaned_url) > 55 else cleaned_url
            return (
                f"**Task Queued** • `#job_{job_id}`\n"
                f"\n\n"
                f"• **Magnet**: `{magnet_disp}`\n"
                f"• **Engine**: `aria2c`"
            )

    is_gdrive = (
        cleaned_url.startswith("gdrive:") or
        cleaned_url.startswith("gd2tg:") or
        "drive.google.com" in cleaned_url or
        "docs.google.com" in cleaned_url
    )
    if is_gdrive:
        gdrive_disp = cleaned_url
        for prefix in ("gdrive:", "gd2tg:"):
            if gdrive_disp.startswith(prefix):
                gdrive_disp = gdrive_disp[len(prefix):]
        gdrive_disp = gdrive_disp[:50] + "..." if len(gdrive_disp) > 50 else gdrive_disp
        return (
            f"**Task Queued** • `#job_{job_id}`\n"
            f"\n\n"
            f"• **Type**: `Google Drive Download`\n"
            f"• **Engine**: `Google Drive API`\n"
            f"• **Link**: `{gdrive_disp}`{args_display}"
        )

    return (
        f"**Task Queued** • `#job_{job_id}`\n"
        f"\n\n"
        f"• **URL**: {format_url_display(url)}{args_display}\n"
        f"• **Engine**: `gallery-dl`"
    )


def compile_unzip_download_status_text(job_id: str, filename: str, current: int, total: int) -> str:
    pct = current * 100.0 / total if total > 0 else 0.0
    bar = make_progress_bar(pct)
    return (
        f"**Task Active** • `#job_{job_id}`\n"
        f"\n\n"
        f"• **Archive**: `{filename}`\n"
        f"• **Progress**: `{pct:.1f}%` `[{bar}]`\n"
        f"• **Downloaded**: `{format_size(current)} / {format_size(total)}`"
    )


def compile_archive_prompt_text(job_id: str, filename: str) -> str:
    return (
        f"**Archive Handling Prompt** • `#job_{job_id}`\n"
        f"\n\n"
        f"• **File**: `{filename}`\n\n"
        "Choose whether to upload the archive file only or extract its contents and upload both:"
    )


def compile_archive_choice_status_text(job_id: str, filename: str, choice_str: str) -> str:
    return (
        f"**Archive Action Confirmed** • `#job_{job_id}`\n"
        f"\n\n"
        f"• **File**: `{filename}`\n"
        f"• **Selection**: `{choice_str}`\n\n"
        "Processing selected operation..."
    )


def compile_conversion_prompt_text(job_id: str, filename: str) -> str:
    return (
        f"**Media Conversion Prompt** • `#job_{job_id}`\n"
        f"\n\n"
        f"• **File**: `{filename}`\n\n"
        "Convert video to MP4 first or upload original document?"
    )


def compile_audio_conversion_prompt_text(job_id: str, filename: str) -> str:
    return (
        f"**Audio Processing Prompt** • `#job_{job_id}`\n"
        f"\n\n"
        f"• **File**: `{filename}`\n\n"
        "Convert audio to MP3 with Pedalboard mastering or upload original?"
    )


def compile_conversion_choice_status_text(job_id: str, filename: str, choice_str: str) -> str:
    return (
        f"**Media Action Confirmed** • `#job_{job_id}`\n"
        f"\n\n"
        f"• **File**: `{filename}`\n"
        f"• **Selection**: `{choice_str}`"
    )


def compile_extraction_status_text(job_id: str, filename: str) -> str:
    return (
        f"**Archive Extraction Active** • `#job_{job_id}`\n"
        f"\n\n"
        f"Extracting `{filename}`..."
    )


def compile_conversion_running_status_text(job_id: str, filename: str) -> str:
    return (
        f"**Media Transcoding Active** • `#job_{job_id}`\n"
        f"\n\n"
        f"Transcoding `{filename}` to MP4 container..."
    )


def compile_audio_conversion_running_status_text(job_id: str, filename: str) -> str:
    return (
        f"**Audio Processing Active** • `#job_{job_id}`\n"
        f"\n\n"
        f"Mastering & transcoding `{filename}` to MP3..."
    )


def compile_conversion_failed_status_text(job_id: str, filename: str) -> str:
    return (
        f"**Conversion Failed** • `#job_{job_id}`\n"
        f"\n\n"
        f"Failed to transcode `{filename}`. Uploading original file."
    )


def compile_audio_conversion_failed_status_text(job_id: str, filename: str) -> str:
    return (
        f"**Audio Processing Failed** • `#job_{job_id}`\n"
        f"\n\n"
        f"Failed to process `{filename}`. Uploading original file."
    )


def compile_extraction_failed_status_text(job_id: str, filename: str) -> str:
    return (
        f"**Extraction Failed** • `#job_{job_id}`\n"
        f"\n\n"
        f"Failed to extract `{filename}`."
    )


def compile_extraction_success_status_text(job_id: str, filename: str) -> str:
    return (
        f"**Archive Extracted** • `#job_{job_id}`\n"
        f"\n\n"
        f"Successfully extracted `{filename}`."
    )


def format_user_args(args_raw: Optional[str]) -> str:
    if not args_raw:
        return ""
    try:
        data = json.loads(args_raw)
        if isinstance(data, list):
            user_flags = [str(item) for item in data if item]
            return " ".join(user_flags)
        elif isinstance(data, dict):
            user_flags = []
            fmt = data.get("archive_format")
            if fmt:
                user_flags.append(f"-{fmt}")
            if data.get("mirror_pixeldrain"):
                user_flags.append("-pd")
            extra = data.get("custom_args") or data.get("extra_args")
            if isinstance(extra, list):
                user_flags.extend([str(x) for x in extra])
            elif isinstance(extra, str) and extra:
                user_flags.append(extra)
            return " ".join(user_flags)
    except Exception:
        return str(args_raw).strip()
    return ""


def compile_job_status_text(job: Job, job_state: JobState) -> str:
    cleaned_url = job.url
    if job.url.startswith("[") and job.url.endswith("]"):
        try:
            parsed = json.loads(job.url)
            if parsed and isinstance(parsed, list):
                cleaned_url = parsed[0]
        except Exception:
            pass

    is_torrent = (
        cleaned_url.startswith("magnet:") or
        cleaned_url.startswith("torrent:") or
        cleaned_url.endswith(".torrent") or
        "magnet:?xt=" in cleaned_url
    )

    is_gdrive = (
        cleaned_url.startswith("gdrive:") or
        cleaned_url.startswith("gd2tg:") or
        "drive.google.com" in cleaned_url or
        "docs.google.com" in cleaned_url
    )

    status_icon = "⚡" if job.status == "downloading" else ("📤" if job.status == "uploading" else "⏳")
    split_str = "Enabled (2GB)" if job.split_large_files else "Disabled"

    lines = [
        f"**Task Execution Details** • `#job_{job.id}`",
        f"\n",
        f"• **Status**: {status_icon} `{job.status.upper()}`",
    ]

    if is_torrent:
        torrent_name = getattr(job_state, "torrent_name", None)
        if torrent_name:
            lines.append(f"• **Torrent**: `{torrent_name}`")
        elif cleaned_url.startswith("torrent:"):
            torrent_path = cleaned_url[len("torrent:"):]
            name = Path(torrent_path).name
            lines.append(f"• **File**: `{name}`")
        else:
            magnet_disp = cleaned_url[:50] + "..." if len(cleaned_url) > 50 else cleaned_url
            lines.append(f"• **Magnet**: `{magnet_disp}`")
    else:
        lines.append(f"• **Target**: {format_url_display(job.url)}")
        user_args_str = format_user_args(job.args)
        if user_args_str:
            lines.append(f"• **Args**: `{user_args_str}`")

    lines.append(f"• **Auto Split**: `{split_str}`")
    lines.append(f"\n")

    if not job_state.downloader_done.is_set():
        dl_speed_str = format_size(job_state.download_speed)
        dl_bytes_str = format_size(job_state.total_downloaded_bytes)
        dl_tool = "Google Drive API" if is_gdrive else ("aria2c" if is_torrent else ("Pyrogram Downloader" if cleaned_url.startswith("unzip:") else "gallery-dl"))

        if is_gdrive:
            marquee = make_marquee_bar()
            lines.append(
                f"**GDrive Download Metrics**\n"
                f"• **Engine**: `{dl_tool}`\n"
                f"• **State**: `[{marquee}]`\n"
                f"• **Downloaded**: `{dl_bytes_str}`\n"
                f"• **Speed**: `{dl_speed_str}/s`"
            )
            if job_state.current_download_file:
                lines.append(f"• **Current**: `{job_state.current_download_file}`")
        elif is_torrent:
            bar = make_progress_bar(job_state.download_pct)
            seeders = getattr(job_state, "torrent_seeders", 0)
            peers = getattr(job_state, "torrent_peers", 0)
            lines.append(
                f"**Torrent Download Metrics**\n"
                f"• **Engine**: `{dl_tool}`\n"
                f"• **Progress**: `{job_state.download_pct:.1f}%` `[{bar}]`\n"
                f"• **Downloaded**: `{dl_bytes_str}`\n"
                f"• **Speed**: `{dl_speed_str}/s`\n"
                f"• **Swarm**: `Seeders: {seeders} | Leechers: {peers}`"
            )
        else:
            marquee = make_marquee_bar()
            lines.append(
                f"**Downloader Metrics**\n"
                f"• **Engine**: `{dl_tool}`\n"
                f"• **Downloaded Count**: `{job_state.download_count}`\n"
                f"• **State**: `[{marquee}]`\n"
                f"• **Total Size**: `{dl_bytes_str}`\n"
                f"• **Speed**: `{dl_speed_str}/s`"
            )
            if job_state.current_download_file:
                lines.append(f"• **Current**: `{job_state.current_download_file}`")
    elif getattr(job_state, "is_archiving", False):
        import shutil
        archiver_tool = "7z" if shutil.which("7z") else ("zip" if shutil.which("zip") else "zipfile")
        fmt = getattr(job_state, "archive_format", "ZIP") or "ZIP"
        lines.append(
            f"**Archive Compression**\n"
            f"• **Engine**: `{archiver_tool}`\n"
            f"• **Format**: `{fmt.upper()}`\n"
            f"• **Status**: `Compressing downloaded folder structure...`"
        )
    elif getattr(job_state, "is_converting", False):
        conv_file = getattr(job_state, "conversion_file", "media file")
        lines.append(
            f"**Media Transcoding**\n"
            f"• **Engine**: `FFmpeg / PyAV`\n"
            f"• **Converting**: `{conv_file}`\n"
            f"• **Status**: `Transcoding to standard MP4 container...`"
        )
    elif job.status == "uploading" or job_state.sent > 0 or job_state.current_upload_file:
        ul_speed_str = format_size(job_state.upload_speed)
        total_files_disp = job.total_files if job.total_files > 0 else 'Calculating'
        lines.append(
            f"**Telegram Upload Metrics**\n"
            f"• **Engine**: `Pyrogram Uploader`\n"
            f"• **Files Uploaded**: `{job_state.sent} / {total_files_disp}`\n"
            f"• **Files Skipped**: `{len(job_state.skipped)}`"
        )
        if job_state.current_upload_file:
            bar = make_progress_bar(job_state.current_upload_pct)
            lines.append(
                f"• **Current File**: `{job_state.current_upload_file}`\n"
                f"• **Progress**: `{job_state.current_upload_pct:.1f}%` `[{bar}]`\n"
                f"• **Upload Speed**: `{ul_speed_str}/s`"
            )

    return "\n".join(lines)
