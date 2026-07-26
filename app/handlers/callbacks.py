from __future__ import annotations

import logging
from pyrogram import Client, filters
from pyrogram.types import CallbackQuery

from ..middleware import is_job_owner
from ..manager import queue_manager, store
from ..manager.status.compiler import (
    compile_queued_status_text,
    compile_archive_choice_status_text,
    compile_conversion_choice_status_text,
)
from ..manager.archive import (
    _archive_ids,
    _archive_events,
    _archive_choices,
)
from ..conversion import (
    _conversion_ids,
    _conversion_events,
    _conversion_choices,
)

log = logging.getLogger(__name__)


def register_choice_callback_handlers(app: Client) -> None:

    @app.on_callback_query(filters.regex(r"^split_(yes|no):(\w+)$"))
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
            except Exception:
                pass

        queued_text = compile_queued_status_text(job.id, job.url, user_args_display)
        try:
            await query.message.edit_text(queued_text)
        except Exception:
            pass

        await queue_manager.enqueue_job(job.id)

    @app.on_callback_query(filters.regex(r"^archive_(only|ext):(\w+):(.+)$"))
    async def archive_choice_cb(_, query: CallbackQuery) -> None:
        match = query.matches[0]
        choice = match.group(1)
        job_id = match.group(2)
        filename = match.group(3)

        job = await store.get_job(job_id)
        if not job or not is_job_owner(query.message.chat.id, job):
            await query.answer("Unauthorized.", show_alert=True)
            return

        choice_str = "Archive Only" if choice == "only" else "Extract & Upload Both"
        await query.answer(f"Selected: {choice_str}")

        try:
            await query.message.edit_text(compile_archive_choice_status_text(job.id, filename, choice_str))
        except Exception:
            pass

        event = _archive_events.get(job.id)
        if event:
            _archive_choices[job.id] = choice
            event.set()

    @app.on_callback_query(filters.regex(r"^convert_(mp4|mp3|orig):(\w+):(.+)$"))
    async def conversion_choice_cb(_, query: CallbackQuery) -> None:
        match = query.matches[0]
        choice = match.group(1)
        job_id = match.group(2)
        filename = match.group(3)

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

        await query.answer(f"Selected: {choice_str}")

        try:
            await query.message.edit_text(compile_conversion_choice_status_text(job.id, filename, choice_str))
        except Exception:
            pass

        event = _conversion_events.get(job.id)
        if event:
            _conversion_choices[job.id] = choice
            event.set()
