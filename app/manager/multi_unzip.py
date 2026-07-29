from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

from pyrogram import Client
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..config import settings
from ..db import JobStatus, JobStore
from .archive import ARCHIVE_EXT, get_split_archive_info
from .status import (
    compile_queued_status_text,
    compile_split_prompt_text,
    compile_unzip_download_status_text,
)
from .status.messaging import format_size

log = logging.getLogger(__name__)

_multi_archive_sessions: dict[int, dict] = {}


def compile_multi_session_text(archives: list[Message]) -> str:
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
    is_archive = ext in ARCHIVE_EXT or get_split_archive_info(filename) is not None
    if not is_archive:
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
    total_archives = len(archives)

    args_json = json.dumps({"password": password}) if password else None

    try:
        await status_msg.edit_text(
            f"**Multi Archive Pipeline Started** ({total_archives} archives)\n"
            "------------------------------------\n"
            "Downloading & processing each archive as it arrives..."
        )
    except Exception:
        pass

    for idx, arch_msg in enumerate(archives, start=1):
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
                    progress_name = f"{arch_filename} ({idx}/{total_archives})"
                    await status_msg.edit_text(
                        compile_unzip_download_status_text(job.id, progress_name, current, total),
                        reply_markup=keyboard
                    )
                except Exception:
                    pass

            target_file = dest_dir / arch_filename
            log.info("Multi-unzip pipeline [%s/%s]: Downloading %s for job #%s...", idx, total_archives, arch_filename, job.id)
            await arch_msg.download(
                file_name=str(target_file),
                progress=on_download_progress
            )

            log.info("Multi-unzip pipeline [%s/%s]: %s downloaded. Enqueuing job #%s immediately!", idx, total_archives, arch_filename, job.id)
            await store.db.execute(
                "UPDATE jobs SET status = ?, split_large_files = ? WHERE id = ?",
                (JobStatus.QUEUED, 1, job.id)
            )
            await store.db.commit()

            # Enqueue to queue_manager so extraction & upload starts
            await queue_manager.add_job(job.id)

            # Wait for this archive job to complete extraction and upload
            # before starting the next archive to prevent intermixing uploaded files
            log.info("Multi-unzip pipeline [%s/%s]: Waiting for job #%s to finish before starting next...", idx, total_archives, job.id)
            while True:
                db_job = await store.get_job(job.id)
                if not db_job or db_job.status in (JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED):
                    job_status = db_job.status if db_job else "UNKNOWN"
                    log.info("Multi-unzip pipeline [%s/%s]: Job #%s finished with status %s", idx, total_archives, job.id, job_status)
                    break
                await asyncio.sleep(1.5)

        except Exception as e:
            log.exception("Multi-unzip pipeline [%s/%s]: Error downloading archive %s", idx, total_archives, arch_filename)
            await store.update_progress(job.id, status=JobStatus.FAILED, error=str(e), url="")

    try:
        await status_msg.edit_text(
            f"**Multi Archive Pipeline Complete**\n"
            f"Successfully processed all {total_archives} archive(s) sequentially."
        )
    except Exception:
        pass
