from __future__ import annotations

import logging
from pathlib import Path

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery

from ..utils.archive import archive_session_store
from ..auth import authorized_filter
from ..conversion import (
    _conversion_choices,
    _conversion_events,
    _conversion_ids,
)
from ..manager import queue_manager, store
from ..manager.status.compiler import (
    compile_archive_choice_status_text,
    compile_conversion_choice_status_text,
    compile_queued_status_text,
)
from ..middleware import is_job_owner

log = logging.getLogger(__name__)


def register_choice_callback_handlers(app: Client) -> None:

    @app.on_callback_query(filters.regex(r"^split_(yes|no):(\w+)$") & authorized_filter)
    async def split_choice_cb(_, query: CallbackQuery) -> None:
        match = query.matches[0]
        choice = match.group(1)
        job_id = match.group(2)
        chat_id = query.message.chat.id

        job = await store.get_job(job_id)
        if not job:
            await query.answer("Job not found.", show_alert=True)
            return

        if not is_job_owner(chat_id, job):
            await query.answer("You are not authorized for this job.", show_alert=True)
            return

        split_val = 1 if choice == "yes" else 0
        await store.db.execute(
            "UPDATE jobs SET status = ?, split_large_files = ? WHERE id = ?",
            ("queued", split_val, job.id)
        )
        await store.db.commit()

        await query.answer(f"Selected: {'Split > 2GB' if split_val else 'Skip > 2GB'}")

        user_args_display = ""
        if job.args:
            try:
                import json
                parsed_args = json.loads(job.args)
                if isinstance(parsed_args, list):
                    user_args_display = f" (Args: `{' '.join(parsed_args)}`)"
            except Exception as e:
                log.debug("Failed parsing job.args JSON in callback: %s", e)

        queued_text = compile_queued_status_text(job.id, job.url, user_args_display)
        try:
            await query.message.edit_text(queued_text)
        except Exception:
            # expected: message text already up to date or deleted
            pass

        await queue_manager.add_job(job.id)

    @app.on_callback_query(filters.regex(r"^archive_(only|ext):(\w+):(.+)$") & authorized_filter)
    async def archive_choice_cb(_, query: CallbackQuery) -> None:
        match = query.matches[0]
        choice = match.group(1)
        job_id = match.group(2)
        archive_id = match.group(3)

        job = await store.get_job(job_id)
        if not job or not is_job_owner(query.message.chat.id, job):
            await query.answer("Unauthorized.", show_alert=True)
            return

        choice_str = "Archive Only" if choice == "only" else "Extract & Upload Both"
        await query.answer(f"Selected: {choice_str}")

        filename = archive_session_store.get_archive_filename(job.id, archive_id) or archive_id
        display_name = Path(filename).name if filename else archive_id

        try:
            await query.message.edit_text(compile_archive_choice_status_text(job.id, display_name, choice_str))
        except Exception:
            # expected: message text already up to date or deleted
            pass

        archive_session_store.set_choice(job.id, archive_id, choice)
        archive_session_store.set_event(job.id, archive_id)

    @app.on_callback_query(filters.regex(r"^convert_(mp4|mp3|orig):(\w+):(.+)$") & authorized_filter)
    async def conversion_choice_cb(_, query: CallbackQuery) -> None:
        match = query.matches[0]
        choice = match.group(1)
        job_id = match.group(2)
        conv_id = match.group(3)

        job = await store.get_job(job_id)
        if not job or not is_job_owner(query.message.chat.id, job):
            await query.answer("Unauthorized.", show_alert=True)
            return

        if choice == "mp4":
            choice_str = "Convert to MP4"
        elif choice == "mp3":
            choice_str = "Convert to MP3 (Pedalboard Mastered)"
        else:
            choice_str = "Upload Original Document"

        if not isinstance(_conversion_choices.get(job_id), dict):
            _conversion_choices[job_id] = {}
        _conversion_choices[job_id][conv_id] = choice

        if job_id in _conversion_events and conv_id in _conversion_events[job_id]:
            _conversion_events[job_id][conv_id].set()

        filename = _conversion_ids.get(job_id, {}).get(conv_id, conv_id)
        await query.answer(f"Selected: {choice_str}")

        try:
            await query.message.edit_text(compile_conversion_choice_status_text(job_id, filename, choice_str))
        except Exception:
            # expected: message text already up to date or deleted
            pass
