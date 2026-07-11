"""
Main entrypoint. A single background worker processes jobs one at a time
(bunkr and Telegram both punish concurrency), persisting progress to
SQLite so a crash or redeploy mid-1600-file-album resumes cleanly.
"""

from __future__ import annotations

import asyncio
import logging
import logging.handlers
import random
import shutil
from pathlib import Path

from pyrogram import Client, filters, idle
from pyrogram.types import Message

from .config import settings
from .db import Job, JobStatus, JobStore
from .downloader import GalleryDLNotFound, run_with_progress
from .uploader import UploadTooLarge, upload_file

log = logging.getLogger("tgdl_bot")


def setup_logging() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    root = logging.getLogger()
    root.setLevel(level)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    file_handler = logging.handlers.RotatingFileHandler(
        settings.log_dir / "bot.log", maxBytes=10_000_000, backupCount=5
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    # pyrogram is chatty at INFO; keep it at WARNING unless debugging
    logging.getLogger("pyrogram").setLevel(logging.WARNING)


store = JobStore(settings.db_path)
app = Client(
    "tgdl_bot",
    api_id=settings.tg_api_id,
    api_hash=settings.tg_api_hash,
    bot_token=settings.tg_bot_token,
    workdir=str(settings.data_dir),
)
job_queue: asyncio.Queue[int] = asyncio.Queue()
_shutdown_event = asyncio.Event()
_current_job_id: int | None = None


async def safe_edit(chat_id: int, message_id: int, text: str) -> None:
    from pyrogram.errors import FloodWait, MessageNotModified

    try:
        await app.edit_message_text(chat_id, message_id, text)
    except MessageNotModified:
        pass
    except FloodWait as e:
        await asyncio.sleep(e.value + 1)


async def process_job(job: Job) -> None:
    global _current_job_id
    _current_job_id = job.id
    chat_id = job.chat_id
    msg_id = job.status_message_id
    dest_dir = settings.downloads_dir / job.download_dir

    async def report(text: str) -> None:
        if msg_id:
            await safe_edit(chat_id, msg_id, text)

    try:
        await store.update_progress(job.id, status=JobStatus.DOWNLOADING)
        await report(f"Downloading:\n{job.url}\n(rate-limited, large albums take a while)")

        last_reported = 0

        def on_progress(count: int) -> None:
            nonlocal last_reported
            if count - last_reported >= 25:
                last_reported = count
                asyncio.create_task(report(f"Downloading… ~{count} items processed so far"))

        result = await run_with_progress(
            job.url, dest_dir, settings.gdl_archive_path, on_progress=on_progress
        )

        if not result.ok and not result.files:
            await store.update_progress(
                job.id, status=JobStatus.FAILED, error=result.error_tail[-1500:]
            )
            await report(
                f"gallery-dl failed after {result.attempts} attempt(s) and produced no files.\n"
                f"Last output:\n```\n{result.error_tail[-800:]}\n```"
            )
            return

        files = result.files
        already_uploaded = await store.get_uploaded_filenames(job.id)
        pending = [f for f in files if f.name not in already_uploaded]

        await store.update_progress(
            job.id, status=JobStatus.UPLOADING, total_files=len(files), skipped_files=0
        )
        await report(
            f"Downloaded {len(files)} file(s)"
            + (f" ({result.attempts} attempts needed)" if result.attempts > 1 else "")
            + f". Uploading {len(pending)} remaining…"
        )

        sent = len(already_uploaded)
        skipped: list[tuple[str, str]] = []

        for i, f in enumerate(pending, 1):
            if _shutdown_event.is_set():
                await store.update_progress(job.id, status=JobStatus.QUEUED)
                await report("Paused for shutdown — will resume on next start.")
                return

            try:
                await upload_file(app, chat_id, f)
                await store.mark_uploaded(job.id, f.name)
                sent += 1
            except UploadTooLarge as e:
                skipped.append((f.name, str(e)))
            except Exception as e:  # noqa: BLE001 — log and continue the batch
                log.exception("upload failed for %s", f)
                skipped.append((f.name, f"error: {e}"))

            await store.update_progress(job.id, sent_files=sent, skipped_files=len(skipped))

            if i % settings.progress_edit_every_n == 0 or i == len(pending):
                await report(
                    f"Uploading… {i}/{len(pending)} this run, {sent}/{len(files)} total sent, "
                    f"{len(skipped)} skipped."
                )

            if i % settings.tg_batch_size == 0 and i != len(pending):
                await asyncio.sleep(settings.tg_batch_cooldown_s)
            else:
                await asyncio.sleep(
                    random.uniform(settings.tg_upload_delay_min, settings.tg_upload_delay_max)
                )

        await store.update_progress(job.id, status=JobStatus.DONE, sent_files=sent, skipped_files=len(skipped))
        summary = f"Done. Uploaded {sent}/{len(files)} file(s) total."
        if skipped:
            preview = "\n".join(f"- {n} ({info})" for n, info in skipped[:20])
            more = f"\n…and {len(skipped) - 20} more" if len(skipped) > 20 else ""
            summary += f"\nSkipped:\n{preview}{more}"
        await app.send_message(chat_id, summary)

        # cleanup: only remove local files once every one is accounted for
        shutil.rmtree(dest_dir, ignore_errors=True)

    except GalleryDLNotFound as e:
        await store.update_progress(job.id, status=JobStatus.FAILED, error=str(e))
        await report(str(e))
    except Exception as e:  # noqa: BLE001
        log.exception("job %s failed", job.id)
        await store.update_progress(job.id, status=JobStatus.FAILED, error=str(e))
        await report(f"Job failed with an unexpected error: {e}")
    finally:
        _current_job_id = None


async def worker_loop() -> None:
    while not _shutdown_event.is_set():
        try:
            job_id = await asyncio.wait_for(job_queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            continue
        job = await store.get_job(job_id)
        if job is None:
            continue
        await process_job(job)


@app.on_message(filters.command("start"))
async def start_cmd(_, message: Message) -> None:
    await message.reply_text(
        "Send me a link and I'll fetch it with gallery-dl and upload the results here.\n"
        "Large albums are throttled to avoid rate limits — I'll post progress as I go.\n\n"
        "Commands: /status, /cancel"
    )


@app.on_message(filters.command("status"))
async def status_cmd(_, message: Message) -> None:
    if _current_job_id is not None:
        job = await store.get_job(_current_job_id)
        if job:
            await message.reply_text(
                f"Job #{job.id}: {job.status}\n"
                f"{job.sent_files}/{job.total_files} sent, {job.skipped_files} skipped"
            )
            return
    queued = await store.queued_jobs()
    await message.reply_text(f"Nothing running. {len(queued)} job(s) queued." if queued else "Idle. No jobs queued.")


@app.on_message(filters.command("cancel"))
async def cancel_cmd(_, message: Message) -> None:
    if _current_job_id is None:
        await message.reply_text("Nothing is currently running.")
        return
    await store.update_progress(_current_job_id, status=JobStatus.CANCELLED)
    await message.reply_text(
        f"Marked job #{_current_job_id} for cancellation — it'll stop after the current file finishes."
    )


@app.on_message(filters.text & ~filters.command(["start", "status", "cancel"]))
async def handle_link(_, message: Message) -> None:
    text = (message.text or "").strip()
    if not text.startswith(("http://", "https://")):
        await message.reply_text("Send an actual URL.")
        return

    job = await store.create_job(message.chat.id, text)
    status_msg = await message.reply_text(f"Queued (job #{job.id}).")
    await store.set_status_message(job.id, status_msg.id)
    await job_queue.put(job.id)


async def requeue_incomplete_jobs() -> None:
    """On startup, put back-in-progress and queued jobs onto the queue so
    interrupted runs resume instead of silently vanishing."""
    for job in [*await store.resumable_jobs(), *await store.queued_jobs()]:
        log.info("Resuming job #%s (%s)", job.id, job.status)
        await job_queue.put(job.id)


async def _startup() -> None:
    await store.open()
    await requeue_incomplete_jobs()


async def main() -> None:
    """
    Kurigram/Pyrogram's Client binds to whatever event loop exists at
    construction time (module import, for `app` above). Calling
    asyncio.run() here would spin up a second, unrelated loop and every
    Pyrogram internal await would be attached to the wrong one — that's
    the 'attached to a different loop' crash. Calling app.start()/stop()
    from plain sync code has its own footgun: Pyrogram's sync-mode
    patching detects "no running loop" and executes them immediately,
    returning the Client itself rather than a coroutine, which breaks
    manual run_until_complete() calls.

    Both problems disappear by keeping this as a genuine `async def` and
    launching it with `app.run(main())` at the bottom of the file —
    Pyrogram's run() reuses its own existing loop instead of creating a
    new one, and `await app.start()` inside a real async context behaves
    as a normal coroutine.
    """
    setup_logging()

    if shutil.which("gallery-dl") is None:
        log.warning(
            "gallery-dl not found on PATH — install with "
            "`pip install gallery-dl --break-system-packages`"
        )

    await _startup()
    worker_task = asyncio.create_task(worker_loop())

    async with app:
        log.info("Bot started.")
        await idle()  # blocks until SIGINT/SIGTERM

    log.info("Shutting down, finishing current file then stopping…")
    _shutdown_event.set()
    try:
        await asyncio.wait_for(worker_task, timeout=35)
    except asyncio.TimeoutError:
        worker_task.cancel()
    await store.close()
    log.info("Shutdown complete.")


if __name__ == "__main__":
    # Not asyncio.run() — it unconditionally creates a brand-new event loop,
    # which is what caused the original 'attached to a different loop'
    # crash (the Client had already bound itself to the default loop at
    # construction). get_event_loop() reuses that same default loop instead.
    #
    # Not app.run(main()) either — Kurigram's run() (unlike upstream
    # Pyrogram) doesn't accept a coroutine argument; passing one raises
    # TypeError. Driving the loop ourselves sidesteps that fork difference
    # entirely.
    asyncio.get_event_loop().run_until_complete(main())
