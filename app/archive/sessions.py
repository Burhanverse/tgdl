from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

from pyrogram import Client
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, LinkPreviewOptions

from ..config import settings
from ..db import JobStatus, JobStore
from .core import ARCHIVE_EXT
from .split import get_split_archive_info
log = logging.getLogger(__name__)

_archive_ids: dict[str, dict[str, str]] = {}
_archive_events: dict[str, dict[str, asyncio.Event]] = {}
_archive_choices: dict[str, dict[str, str]] = {}
_extracted_archives: dict[str, set[str]] = {}
_extracted_file_names: dict[str, set[str]] = {}

_multi_archive_sessions: dict[int, dict] = {}
_split_archive_sessions: dict[int, dict] = {}


async def handle_archive_choice(
    callback_query: CallbackQuery,
    store: JobStore,
    is_job_owner_func
) -> None:
    """Handles callback queries when user chooses whether to extract downloaded archives."""
    data = callback_query.data
    parts = data.split(":", 2)
    choice = parts[0].split("_")[1]
    job_id = parts[1]
    archive_id = parts[2]

    job = await store.get_job(job_id)
    if not job:
        await callback_query.answer("Job not found.", show_alert=True)
        return

    if not is_job_owner_func(callback_query.message.chat.id, job):
        await callback_query.answer("Unauthorized: You cannot manage archive choices for this job.", show_alert=True)
        return

    filename = _archive_ids.get(job_id, {}).get(archive_id)
    if not filename:
        await callback_query.answer("Archive choice expired or not found.", show_alert=True)
        return

    if job_id not in _archive_choices:
        _archive_choices[job_id] = {}
    _archive_choices[job_id][archive_id] = choice

    if job_id in _archive_events and archive_id in _archive_events[job_id]:
        _archive_events[job_id][archive_id].set()

    choice_str = "Upload Archive Only" if choice == "only" else "Upload Archive + Extract Contents"
    from ..manager.status.compiler import compile_archive_choice_status_text
    status_text = compile_archive_choice_status_text(job.id, Path(filename).name, choice_str)
    await callback_query.message.edit_text(status_text, link_preview_options=LinkPreviewOptions(is_disabled=True))
    await callback_query.answer(f"Selected: {choice_str}")


def compile_multi_session_text(archives: list[Message]) -> str:
    from ..manager.status.messaging import format_size
    if not archives:
        archives_str = "_Waiting for archive files..._"
    else:
        items = []
        for idx, msg in enumerate(archives, start=1):
            fn = msg.document.file_name or "archive"
            sz = format_size(msg.document.file_size or 0)
            items.append(f"**{idx}.** `{fn}` ({sz})")
        archives_str = "\n".join(items)

    text = (
        f"**Multi Archive Session**\n"
        f"- **Archives Received**: {len(archives)}\n\n"
        f"**Instructions:**\n"
        f"Please upload/forward the archive files (.zip, .rar, .7z, etc.) to this chat.\n\n"
        f"**Archives List:**\n"
        f"{archives_str}\n\n"
        f"When all archives are uploaded, click **Start Extraction** below."
    )
    return text


def get_multi_session_keyboard(chat_id: int, user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Start Extraction", callback_data=f"multi_start:{chat_id}:{user_id}"),
            InlineKeyboardButton("Cancel", callback_data=f"multi_cancel:{chat_id}:{user_id}")
        ]
    ])


async def start_multi_unzip_session(
    message: Message,
    password: Optional[str] = None,
    split_archive_sessions: Optional[dict] = None
) -> None:
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else chat_id
    session_key = chat_id

    log.info("Starting /unzip multi session. chat_id=%s, user_id=%s", chat_id, user_id)

    if split_archive_sessions is not None and session_key in split_archive_sessions:
        old_split = split_archive_sessions.pop(session_key)
        if old_split.get("timeout_task"):
            old_split["timeout_task"].cancel()
        try:
            await old_split["status_msg"].edit_text("**Session replaced by a new one.**")
        except Exception:
            pass

    if session_key in _multi_archive_sessions:
        old_session = _multi_archive_sessions.pop(session_key)
        if old_session.get("timeout_task"):
            old_session["timeout_task"].cancel()
        try:
            await old_session["status_msg"].edit_text("**Session replaced by a new one.**")
        except Exception:
            pass

    status_msg = await message.reply_text(
        "**Multi Archive Session Started**\n\n"
        "Please send or forward the archive files (.zip, .rar, .7z, etc.) to this chat.\n\n"
        "**Waiting for files...**",
        reply_markup=get_multi_session_keyboard(chat_id, user_id)
    )

    async def multi_session_timeout(c_id: int, delay: int = 300):
        await asyncio.sleep(delay)
        s_key = c_id
        if s_key in _multi_archive_sessions:
            session = _multi_archive_sessions.pop(s_key)
            try:
                await session["status_msg"].edit_text("**Multi Archive Session Expired** (Timeout due to inactivity).")
            except Exception:
                pass

    timeout_task = asyncio.create_task(multi_session_timeout(chat_id))

    _multi_archive_sessions[session_key] = {
        "archives": [],
        "status_msg": status_msg,
        "password": password,
        "timeout_task": timeout_task
    }


async def handle_multi_document(message: Message) -> bool:
    chat_id = message.chat.id
    session_key = chat_id
    if session_key not in _multi_archive_sessions:
        return False

    if not message.document:
        return False

    filename = message.document.file_name
    if not filename:
        return False

    ext = Path(filename).suffix.lower()
    is_arch = ext in ARCHIVE_EXT or get_split_archive_info(filename) is not None
    if not is_arch:
        log.debug("Filename %s not recognized as an archive in multi session", filename)
        return False

    session = _multi_archive_sessions[session_key]
    existing_ids = [m.id for m in session["archives"]]
    if message.id not in existing_ids:
        session["archives"].append(message)
        log.info("Added archive %s to multi session for chat %s. Total: %s", filename, chat_id, len(session["archives"]))

    if session.get("timeout_task"):
        session["timeout_task"].cancel()

    async def multi_session_timeout(c_id: int, delay: int = 300):
        await asyncio.sleep(delay)
        s_key = c_id
        if s_key in _multi_archive_sessions:
            expired_session = _multi_archive_sessions.pop(s_key)
            try:
                await expired_session["status_msg"].edit_text("**Multi Archive Session Expired** (Timeout due to inactivity).")
            except Exception:
                pass

    session["timeout_task"] = asyncio.create_task(multi_session_timeout(chat_id))

    keyboard = session["status_msg"].reply_markup
    new_text = compile_multi_session_text(session["archives"])

    try:
        await session["status_msg"].edit_text(new_text, reply_markup=keyboard)
    except Exception:
        pass

    return True


async def handle_multi_cancel_cb(client: Client, callback_query: CallbackQuery) -> None:
    data = callback_query.data
    _, chat_id_str, user_id_str = data.split(":")
    chat_id = int(chat_id_str)
    user_id = int(user_id_str)

    req_user_id = callback_query.from_user.id if callback_query.from_user else callback_query.message.chat.id
    if req_user_id != user_id:
        await callback_query.answer("Unauthorized: You did not start this session.", show_alert=True)
        return

    session_key = chat_id
    if session_key in _multi_archive_sessions:
        session = _multi_archive_sessions.pop(session_key)
        if session.get("timeout_task"):
            session["timeout_task"].cancel()
        await callback_query.message.edit_text("**Multi Archive Session Cancelled.**")
        await callback_query.answer("Session cancelled.")
    else:
        await callback_query.answer("Session not found or already expired.", show_alert=True)


async def handle_multi_start_cb(client: Client, callback_query: CallbackQuery, store: JobStore, queue_manager) -> None:
    data = callback_query.data
    _, chat_id_str, user_id_str = data.split(":")
    chat_id = int(chat_id_str)
    user_id = int(user_id_str)

    req_user_id = callback_query.from_user.id if callback_query.from_user else callback_query.message.chat.id
    if req_user_id != user_id:
        await callback_query.answer("Unauthorized: You did not start this session.", show_alert=True)
        return

    session_key = chat_id
    if session_key not in _multi_archive_sessions:
        await callback_query.answer("Session not found or already expired.", show_alert=True)
        return

    session = _multi_archive_sessions[session_key]
    archives = session["archives"]

    if not archives:
        await callback_query.answer("No archives uploaded yet. Please send some archive files first.", show_alert=True)
        return

    _multi_archive_sessions.pop(session_key)
    if session.get("timeout_task"):
        session["timeout_task"].cancel()

    await callback_query.answer("Starting extraction job...")
    asyncio.create_task(run_multi_archive_download_and_extract(session, callback_query.message, store, queue_manager))


async def run_multi_archive_download_and_extract(
    session: dict,
    status_msg: Message,
    store: JobStore,
    queue_manager
) -> None:
    archives: list[Message] = session["archives"]
    password: Optional[str] = session["password"]
    chat_id = status_msg.chat.id

    if not archives:
        return

    groups: list[dict] = []
    group_map: dict[str, dict] = {}

    for arch_msg in archives:
        fn = arch_msg.document.file_name or "archive"
        split_info = get_split_archive_info(fn)
        if split_info:
            prefix = split_info["prefix"]
            part = split_info["part"]
            if prefix in group_map:
                group_map[prefix]["parts"].append((part, arch_msg))
            else:
                g = {
                    "is_split": True,
                    "prefix": prefix,
                    "parts": [(part, arch_msg)]
                }
                group_map[prefix] = g
                groups.append(g)
        else:
            groups.append({
                "is_split": False,
                "msg": arch_msg
            })

    total_groups = len(groups)
    args_json = json.dumps({"password": password}) if password else None

    try:
        await status_msg.edit_text(
            f"**Multi Archive Pipeline Started** ({total_groups} job(s), {len(archives)} file(s))\n"
            "------------------------------------\n"
            "Downloading & processing each archive..."
        )
    except Exception:
        pass

    for idx, group in enumerate(groups, start=1):
        if group["is_split"]:
            parts_sorted = sorted(group["parts"], key=lambda x: x[0])
            first_msg = parts_sorted[0][1]
            arch_filename = first_msg.document.file_name or f"{group['prefix']}.part1.rar"
            display_name = f"unzip:{arch_filename}"

            job = await store.create_job(chat_id, display_name, split_large_files=1, args=args_json)
            await store.update_progress(job.id, status=JobStatus.DOWNLOADING)

            dest_dir = (settings.downloads_dir / job.download_dir).resolve()
            dest_dir.mkdir(parents=True, exist_ok=True)

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("Cancel", callback_data=f"cancel_job:{job.id}")]
            ])

            try:
                import time
                last_edit_time = 0.0
                total_parts_in_group = len(parts_sorted)
                for part_idx, (part_num, p_msg) in enumerate(parts_sorted, start=1):
                    p_filename = p_msg.document.file_name or f"part_{part_num}"
                    target_file = dest_dir / p_filename

                    async def on_split_part_progress(current, total):
                        nonlocal last_edit_time
                        now = time.time()
                        if now - last_edit_time < 2.0 and current != total:
                            return
                        last_edit_time = now
                        try:
                            from ..manager.status.compiler import compile_unzip_download_status_text
                            progress_name = f"{p_filename} (part {part_idx}/{total_parts_in_group}, job {idx}/{total_groups})"
                            await status_msg.edit_text(
                                compile_unzip_download_status_text(job.id, progress_name, current, total),
                                reply_markup=keyboard
                            )
                        except Exception:
                            pass

                    log.info("Multi-unzip pipeline [%s/%s]: Downloading split part %s for job #%s...", idx, total_groups, p_filename, job.id)
                    await p_msg.download(file_name=str(target_file), progress=on_split_part_progress)

                from .split import normalize_split_archive_filenames
                normalize_split_archive_filenames(dest_dir)

                log.info("Multi-unzip pipeline [%s/%s]: All parts downloaded for split archive job #%s. Enqueuing!", idx, total_groups, job.id)
                await store.db.execute(
                    "UPDATE jobs SET status = ?, split_large_files = ? WHERE id = ?",
                    (JobStatus.QUEUED, 1, job.id)
                )
                await store.db.commit()
                await queue_manager.add_job(job.id)

                log.info("Multi-unzip pipeline [%s/%s]: Waiting for split job #%s to finish...", idx, total_groups, job.id)
                while True:
                    db_job = await store.get_job(job.id)
                    if not db_job or db_job.status in (JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED):
                        job_status = db_job.status if db_job else "UNKNOWN"
                        log.info("Multi-unzip pipeline [%s/%s]: Job #%s finished with status %s", idx, total_groups, job.id, job_status)
                        break
                    await asyncio.sleep(1.5)

            except Exception as e:
                log.exception("Multi-unzip pipeline [%s/%s]: Error processing split archive %s", idx, total_groups, arch_filename)
                await store.update_progress(job.id, status=JobStatus.FAILED, error=str(e), url="")

        else:
            arch_msg = group["msg"]
            arch_filename = arch_msg.document.file_name or f"archive_{idx}.zip"
            display_name = f"unzip:{arch_filename}"

            job = await store.create_job(chat_id, display_name, split_large_files=1, args=args_json)
            await store.update_progress(job.id, status=JobStatus.DOWNLOADING)

            dest_dir = (settings.downloads_dir / job.download_dir).resolve()
            dest_dir.mkdir(parents=True, exist_ok=True)

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("Cancel", callback_data=f"cancel_job:{job.id}")]
            ])

            try:
                last_edit_time = 0.0
                async def on_download_progress(current, total):
                    nonlocal last_edit_time
                    import time
                    now = time.time()
                    if now - last_edit_time < 2.5 and current != total:
                        return
                    last_edit_time = now
                    try:
                        from ..manager.status.compiler import compile_unzip_download_status_text
                        progress_name = f"{arch_filename} ({idx}/{total_groups})"
                        await status_msg.edit_text(
                            compile_unzip_download_status_text(job.id, progress_name, current, total),
                            reply_markup=keyboard
                        )
                    except Exception:
                        pass

                target_file = dest_dir / arch_filename
                log.info("Multi-unzip pipeline [%s/%s]: Downloading %s for job #%s...", idx, total_groups, arch_filename, job.id)
                await arch_msg.download(
                    file_name=str(target_file),
                    progress=on_download_progress
                )

                log.info("Multi-unzip pipeline [%s/%s]: %s downloaded. Enqueuing job #%s immediately!", idx, total_groups, arch_filename, job.id)
                await store.db.execute(
                    "UPDATE jobs SET status = ?, split_large_files = ? WHERE id = ?",
                    (JobStatus.QUEUED, 1, job.id)
                )
                await store.db.commit()
                await queue_manager.add_job(job.id)

                log.info("Multi-unzip pipeline [%s/%s]: Waiting for job #%s to finish before starting next...", idx, total_groups, job.id)
                while True:
                    db_job = await store.get_job(job.id)
                    if not db_job or db_job.status in (JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED):
                        job_status = db_job.status if db_job else "UNKNOWN"
                        log.info("Multi-unzip pipeline [%s/%s]: Job #%s finished with status %s", idx, total_groups, job.id, job_status)
                        break
                    await asyncio.sleep(1.5)

            except Exception as e:
                log.exception("Multi-unzip pipeline [%s/%s]: Error downloading archive %s", idx, total_groups, arch_filename)
                await store.update_progress(job.id, status=JobStatus.FAILED, error=str(e), url="")

    try:
        await status_msg.edit_text(
            f"**Multi Archive Pipeline Complete**\n"
            f"Successfully processed all {total_groups} job(s) sequentially."
        )
    except Exception:
        pass
