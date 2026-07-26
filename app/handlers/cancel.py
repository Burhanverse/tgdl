from __future__ import annotations

import logging
from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from ..middleware import is_job_owner
from ..manager.core import queue_manager, store
from ..db import JobStatus

log = logging.getLogger(__name__)


def register_cancel_handlers(app: Client) -> None:

    @app.on_message(filters.command("cancel"))
    async def cancel_cmd(_, message: Message) -> None:
        chat_id = message.chat.id
        
        cmd_parts = message.text.split()
        if len(cmd_parts) > 1:
            job_id = cmd_parts[1].strip()

            job = await store.get_job(job_id)
            if not job or not is_job_owner(chat_id, job):
                await message.reply_text(f"Job #{job_id} not found or not owned by you.")
                return

            if job.status in (JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED):
                await message.reply_text(f"Job #{job_id} is already in `{job.status}` state.")
                return

            cancelled = await queue_manager.cancel_job(job.id)
            if cancelled:
                await message.reply_text(f"Instantly aborted and cancelled active job #{job.id}.")
            else:
                await store.update_progress(job.id, status=JobStatus.CANCELLED)
                await message.reply_text(f"Job #{job.id} has been cancelled successfully.")
            return

        cur = await store.db.execute(
            "SELECT id, url, status FROM jobs WHERE chat_id = ? AND status IN ('queued', 'waiting', 'downloading', 'uploading')",
            (chat_id,)
        )
        rows = await cur.fetchall()
        if not rows:
            await message.reply_text("No active or queued jobs found for this chat.")
            return

        if len(rows) == 1:
            job_id = rows[0]["id"]
            job_status = rows[0]["status"]
            cancelled = await queue_manager.cancel_job(job_id)
            if not cancelled:
                await store.update_progress(job_id, status=JobStatus.CANCELLED)
            await message.reply_text(f"Job #{job_id} ({job_status}) has been cancelled.")
            return

        buttons = []
        for r in rows:
            jid = r["id"]
            url = r["url"]
            jstatus = r["status"]
            label = url.split(":", 1)[1] if ":" in url else url
            label = label.split("/")[-1] or label
            if len(label) > 25:
                label = label[:22] + "…"
                
            btn_text = f"#{jid} - {label} ({jstatus})"
            buttons.append([InlineKeyboardButton(btn_text, callback_data=f"cancel_job:{jid}")])

        await message.reply_text(
            "**Select a job to cancel:**",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    @app.on_callback_query(filters.regex(r"^cancel_job:(\w+)$"))
    async def cancel_job_cb(_, query: CallbackQuery) -> None:
        match = query.matches[0]
        job_id = match.group(1)
        chat_id = query.message.chat.id

        job = await store.get_job(job_id)
        if not job:
            await query.answer("Job not found.", show_alert=True)
            return

        if not is_job_owner(chat_id, job):
            await query.answer("You are not authorized to cancel this job.", show_alert=True)
            return

        if job.status in (JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED):
            await query.answer(f"Job #{job.id} is already {job.status}.", show_alert=True)
            return

        await query.answer(f"Cancelling job #{job.id}...")
        cancelled = await queue_manager.cancel_job(job.id)
        if not cancelled:
            await store.update_progress(job.id, status=JobStatus.CANCELLED)

        try:
            await query.message.edit_text(
                f"**Job #{job.id} Cancelled**\n"
                "------------------------------------\n"
                "Cancelled successfully by user."
            )
        except Exception:
            pass
