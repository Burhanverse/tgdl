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
    bar = ["○"] * width
    bar[pos] = "●"
    return "".join(bar)

def format_url_display(url_json: str, current_url: Optional[str] = None) -> str:
    def _clean(u: str) -> str:
        u_str = str(u).strip()
        if u_str.startswith("direct:"):
            return u_str[len("direct:"):]
        if u_str.startswith("mirror:"):
            return u_str[len("mirror:"):]
        return u_str

    def _format_single(u: str, suffix: str = "") -> str:
        clean_u = _clean(u)
        suffix_str = f" {suffix}" if suffix else ""
        return f"{clean_u}{suffix_str}"

    try:
        urls = json.loads(url_json)
        if isinstance(urls, list):
            clean_urls = [_clean(u) for u in urls if str(u).strip()]
            if current_url:
                clean_curr = _clean(current_url)
                if clean_curr in clean_urls:
                    idx = clean_urls.index(clean_curr) + 1
                    return _format_single(clean_curr, f"(Item {idx} of {len(clean_urls)})")
                return _format_single(clean_curr)
            if len(clean_urls) == 1:
                return _format_single(clean_urls[0])
            if len(clean_urls) > 1:
                return _format_single(clean_urls[0], f"(+ {len(clean_urls) - 1} more)")
    except Exception:
        pass

    target_u = current_url or url_json
    return _format_single(target_u)


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
        f"> {title}\n"
        f"> • **__{target_label}__**: {display}\n\n"
        "__Do you want to split files larger than 2GB for this job?__"
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
                f"**Task #{job_id} Queued**\n"
                f"> • **__Torrent__**: __`{name}`__\n"
                f"> • **__Engine__**: __`aria2c`__"
            )
        else:
            return (
                f"**Task #{job_id} Queued**\n"
                f"> • **__Magnet__**:\n"
                f"**>**\n`{cleaned_url}`||\n"
                f"> • **__Engine__**: __`aria2c`__"
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
            f"**Task #{job_id} Queued**\n"
            f"> • **__Type__**: __`Google Drive Download`__\n"
            f"> • **__Engine__**: __`Google Drive API`__\n"
            f"> • **__Link__**: __`{gdrive_disp}`__{args_display}"
        )

    is_direct = (
        cleaned_url.startswith("direct:") or
        '"direct:' in cleaned_url or
        "['direct:" in cleaned_url or
        "direct:" in url
    )

    engine_name = "Direct HTTP Downloader" if is_direct else "gallery-dl"

    return (
        f"**Task #{job_id} Queued**\n"
        f"> • **__URL__**: {format_url_display(url)}{args_display}\n"
        f"> • **__Engine__**: __`{engine_name}`__"
    )


def compile_unzip_download_status_text(job_id: str, filename: str, current: int, total: int) -> str:
    pct = current * 100.0 / total if total > 0 else 0.0
    bar = make_progress_bar(pct)
    return (
        f"**Task #{job_id} Active**\n\n"
        f"> • **Archive**: `{filename}`\n"
        f"> • **Progress**: `{pct:.1f}%` `[{bar}]`\n"
        f"> • **Downloaded**: `{format_size(current)} / {format_size(total)}`"
    )


def compile_archive_prompt_text(job_id: str, filename: str) -> str:
    return (
        f"**Archive Handling Prompt**\n\n"
        f"> • **File**: `{filename}`\n\n"
        "> __Choose whether to upload the archive file only or extract its contents and upload both:__"
    )


def compile_archive_choice_status_text(job_id: str, filename: str, choice_str: str) -> str:
    return (
        f"**Archive Action Confirmed**\n\n"
        f"> • **File**: `{filename}`\n"
        f"> • **Selection**: `{choice_str}`\n\n"
        "> __Processing selected operation...__"
    )


def compile_conversion_prompt_text(job_id: str, filename: str) -> str:
    return (
        f"**Media Conversion Prompt**\n\n"
        f"> • **File**: `{filename}`\n\n"
        "> __Convert video to MP4 first or upload original document?__"
    )


def compile_audio_conversion_prompt_text(job_id: str, filename: str) -> str:
    return (
        f"**Audio Processing Prompt**\n\n"
        f"> • **File**: `{filename}`\n\n"
        "> __Convert audio to MP3 with Pedalboard mastering or upload original?__"
    )


def compile_conversion_choice_status_text(job_id: str, filename: str, choice_str: str) -> str:
    return (
        f"**Media Action Confirmed**\n\n"
        f"> • **File**: `{filename}`\n"
        f"> • **Selection**: `{choice_str}`"
    )


def compile_extraction_status_text(job_id: str, filename: str) -> str:
    return (
        f"**Archive Extraction Active**\n\n"
        f"> • **Extracting**: `{filename}`"
    )


def compile_conversion_running_status_text(job_id: str, filename: str) -> str:
    return (
        f"**Media Transcoding Active**\n\n"
        f"> • **Transcoding**: `{filename}` to MP4 container..."
    )


def compile_audio_conversion_running_status_text(job_id: str, filename: str) -> str:
    return (
        f"**Audio Processing Active**\n\n"
        f"> • **Mastering**: `{filename}` to MP3..."
    )


def compile_conversion_failed_status_text(job_id: str, filename: str) -> str:
    return (
        f"**Conversion Failed**\n\n"
        f"> • **Notice**: Failed to transcode `{filename}`. Uploading original file."
    )


def compile_audio_conversion_failed_status_text(job_id: str, filename: str) -> str:
    return (
        f"**Audio Processing Failed**\n\n"
        f"> • **Notice**: Failed to process `{filename}`. Uploading original file."
    )


def compile_extraction_failed_status_text(job_id: str, filename: str) -> str:
    return (
        f"**Extraction Failed**\n\n"
        f"> • **Notice**: Failed to extract `{filename}`."
    )


def compile_extraction_success_status_text(job_id: str, filename: str) -> str:
    return (
        f"**Archive Extracted**\n\n"
        f"> • **Notice**: Successfully extracted `{filename}`."
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

    is_direct = (
        cleaned_url.startswith("direct:") or
        '"direct:' in cleaned_url or
        "['direct:" in cleaned_url or
        job.url.startswith("direct:") or
        '"direct:' in job.url
    )

    split_str = "Enabled (2GB)" if job.split_large_files else "Disabled"

    lines = [
        f"**Task #{job.id} Details**\n",
        f"> • **__Status__**: __`{job.status.upper()}`__",
    ]

    if is_torrent:
        torrent_name = getattr(job_state, "torrent_name", None)
        if torrent_name:
            lines.append(f"> • **__Torrent__**: __`{torrent_name}`__")
        elif cleaned_url.startswith("torrent:"):
            torrent_path = cleaned_url[len("torrent:"):]
            name = Path(torrent_path).name
            lines.append(f"> • **__File__**: __`{name}`__")
        else:
            lines.append(f"> • **__Magnet__**: `{cleaned_url}`")
    else:
        cur_url = getattr(job_state, "current_download_url", None)
        lines.append(f"> • **__Target__**: {format_url_display(job.url, current_url=cur_url)}")
        user_args_str = format_user_args(job.args)
        if user_args_str:
            lines.append(f"> • **__Args__**: __`{user_args_str}`__")

    lines.append(f"> • **__Auto Split__**: __`{split_str}`__\n")

    if not job_state.downloader_done.is_set():
        dl_speed_str = format_size(job_state.download_speed)
        dl_bytes_str = format_size(job_state.total_downloaded_bytes)
        dl_tool = "Google Drive API" if is_gdrive else ("aria2c" if is_torrent else ("Direct HTTP Downloader" if is_direct else ("Pyrogram Downloader" if cleaned_url.startswith("unzip:") else "gallery-dl")))

        if is_gdrive:
            marquee = make_marquee_bar()
            lines.append(
                f"**Downloader Metrics**\n"
                f"> • **__Engine__**: __`{dl_tool}`__\n"
                f"> • **__State__**: __`[{marquee}]`__\n"
                f"> • **__Downloaded__**: __`{dl_bytes_str}`__\n"
                f"> • **__Speed__**: __`{dl_speed_str}/s`__"
            )
            if job_state.current_download_file:
                lines.append(f"> • **__Current__**: __`{job_state.current_download_file}`__")
        elif is_torrent:
            bar = make_progress_bar(job_state.download_pct)
            seeders = getattr(job_state, "torrent_seeders", 0)
            peers = getattr(job_state, "torrent_peers", 0)
            lines.append(
                f"**Downloader Metrics**\n"
                f"> • **__Engine__**: __`{dl_tool}`__\n"
                f"> • **__Progress__**: __`{job_state.download_pct:.1f}%` `[{bar}]`__\n"
                f"> • **__Downloaded__**: __`{dl_bytes_str}`__\n"
                f"> • **__Speed__**: __`{dl_speed_str}/s`__\n"
                f"> • **__Swarm__**: __`Seeders: {seeders} | Leechers: {peers}`__"
            )
        elif is_direct:
            dl_pct = job_state.download_pct
            total_bytes = getattr(job_state, "total_expected_bytes", 0)
            if dl_pct > 0 or total_bytes > 0:
                bar = make_progress_bar(dl_pct)
                total_str = format_size(total_bytes) if total_bytes > 0 else "Unknown"
                lines.append(
                    f"**Downloader Metrics**\n"
                    f"> • **__Engine__**: __`{dl_tool}`__\n"
                    f"> • **__Progress__**: __`{dl_pct:.1f}%` `[{bar}]`__\n"
                    f"> • **__Downloaded__**: __`{dl_bytes_str} / {total_str}`__\n"
                    f"> • **__Speed__**: __`{dl_speed_str}/s`__"
                )
            else:
                marquee = make_marquee_bar()
                lines.append(
                    f"**Downloader Metrics**\n"
                    f"> • **__Engine__**: __`{dl_tool}`__\n"
                    f"> • **__State__**: __`[{marquee}]`__\n"
                    f"> • **__Downloaded__**: __`{dl_bytes_str}`__\n"
                    f"> • **__Speed__**: __`{dl_speed_str}/s`__"
                )
            if job_state.current_download_file:
                lines.append(f"> • **__Current__**: __`{job_state.current_download_file}`__")
        else:
            dl_pct = job_state.download_pct
            total_bytes = getattr(job_state, "total_expected_bytes", 0)
            if dl_pct > 0 or total_bytes > 0:
                bar = make_progress_bar(dl_pct)
                total_str = format_size(total_bytes) if total_bytes > 0 else "Unknown"
                lines.append(
                    f"**Downloader Metrics**\n"
                    f"> • **__Engine__**: __`{dl_tool}`__\n"
                    f"> • **__Progress__**: __`{dl_pct:.1f}%` `[{bar}]`__\n"
                    f"> • **__Downloaded__**: __`{dl_bytes_str} / {total_str}`__\n"
                    f"> • **__Speed__**: __`{dl_speed_str}/s`__"
                )
            else:
                marquee = make_marquee_bar()
                lines.append(
                    f"**Downloader Metrics**\n"
                    f"> • **__Engine__**: __`{dl_tool}`__\n"
                    f"> • **__Downloaded Count__**: __`{job_state.download_count}`__\n"
                    f"> • **__State__**: __`[{marquee}]`__\n"
                    f"> • **__Total Size__**: __`{dl_bytes_str}`__\n"
                    f"> • **__Speed__**: __`{dl_speed_str}/s`__"
                )
            if job_state.current_download_file:
                lines.append(f"> • **__Current__**: __`{job_state.current_download_file}`__")

    if getattr(job_state, "is_archiving", False):
        if not job_state.downloader_done.is_set():
            lines.append("")
        import shutil
        archiver_tool = "7z" if shutil.which("7z") else ("zip" if shutil.which("zip") else "zipfile")
        fmt = getattr(job_state, "archive_format", "ZIP") or "ZIP"
        lines.append(
            f"**Archive Compression**\n"
            f"> • **__Engine__**: __`{archiver_tool}`__\n"
            f"> • **__Format__**: __`{fmt.upper()}`__\n"
            f"> • **__Status__**: __`Compressing downloaded folder structure...`__"
        )
    elif getattr(job_state, "is_converting", False):
        if not job_state.downloader_done.is_set():
            lines.append("")
        conv_file = getattr(job_state, "conversion_file", "media file")
        lines.append(
            f"**Media Transcoding**\n"
            f"> • **__Engine__**: __`FFmpeg / PyAV`__\n"
            f"> • **__Converting__**: __`{conv_file}`__\n"
            f"> • **__Status__**: __`Transcoding to standard MP4 container...`__"
        )

    web_mirror_info = getattr(job_state, "web_mirror_info", None)
    uploaded_count = getattr(job_state, "sent", 0)
    if isinstance(uploaded_count, (set, list)):
        uploaded_count = len(uploaded_count)
    skipped_count = len(getattr(job_state, "skipped", [])) if isinstance(getattr(job_state, "skipped", []), (list, set)) else getattr(job_state, "skipped", 0)

    is_uploader_active = (
        not job_state.uploader_done.is_set() and (
            job_state.downloader_done.is_set() or
            uploaded_count > 0 or
            len(job_state.uploaded_filenames) > 0 or
            len(job_state.uploading_files) > 0 or
            bool(job_state.current_upload_file) or
            web_mirror_info is not None
        )
    )

    if is_uploader_active:
        if not job_state.downloader_done.is_set() or getattr(job_state, "is_archiving", False) or getattr(job_state, "is_converting", False):
            lines.append("")

        ul_speed_str = format_size(job_state.upload_speed)
        total_files_disp = job.total_files if job.total_files > 0 else 'Calculating'

        if web_mirror_info:
            lines.append("**Mirror Metrics**")
            host_labels = [
                ("gofile", "GoFile"),
                ("fileditch", "FileDitch"),
                ("pixeldrain", "Pixeldrain")
            ]
            for idx, (key, label) in enumerate(host_labels):
                tree = "├" if idx < len(host_labels) - 1 else "└"
                info = web_mirror_info.get(key, {})
                st = info.get("status", "pending")
                url = info.get("url")
                if st == "done" and url:
                    lines.append(f"> {tree} **__[{label}]({url})__**: __`Uploaded`__")
                elif st == "uploading":
                    pct = info.get("pct", 0.0)
                    spd = info.get("speed", 0.0)
                    bar = make_progress_bar(pct)
                    spd_str = f"{format_size(spd)}/s" if spd > 0 else "0 B/s"
                    lines.append(f"> {tree} **__{label}__**: __`{bar}` {pct:.1f}% ({spd_str})__")
                elif st == "skipped":
                    lines.append(f"> {tree} **__{label}__**: __`Skipped (>10GB)`__")
                elif st == "failed":
                    err = info.get("error", "Failed")
                    lines.append(f"> {tree} **__{label}__**: __`{err}`__")
                else:
                    lines.append(f"> {tree} **__{label}__**: __`Pending`__")
        else:
            lines.append(
                f"**Uploader Metrics**\n"
                f"> • **__Engine__**: __`Pyrogram Uploader`__\n"
                f"> • **__Files Uploaded__**: __`{uploaded_count} / {total_files_disp}`__\n"
                f"> • **__Files Skipped__**: __`{skipped_count}`__"
            )
            if job_state.current_upload_file:
                bar = make_progress_bar(job_state.current_upload_pct)
                lines.append(
                    f"> • **__Current File__**: __`{job_state.current_upload_file}`__\n"
                    f"> • **__Progress__**: __`{job_state.current_upload_pct:.1f}%` `[{bar}]`__\n"
                    f"> • **__Speed__**: __`{ul_speed_str}/s`__"
                )

    return "\n".join(lines)
