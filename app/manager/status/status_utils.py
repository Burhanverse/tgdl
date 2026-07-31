from __future__ import annotations

import json
import logging
import time
from html import escape
from pathlib import Path
from typing import Any

from psutil import cpu_percent, disk_usage, virtual_memory

from ...telegram_helper.button_build import ButtonMaker

log = logging.getLogger(__name__)

BOT_START_TIME = time.time()
SIZE_UNITS = ["B", "KB", "MB", "GB", "TB", "PB"]


class MirrorStatus:
    STATUS_UPLOAD = "Upload"
    STATUS_DOWNLOAD = "Download"
    STATUS_CLONE = "Clone"
    STATUS_QUEUEDL = "QueueDl"
    STATUS_QUEUEUP = "QueueUp"
    STATUS_PAUSED = "Pause"
    STATUS_ARCHIVE = "Archive"
    STATUS_EXTRACT = "Extract"
    STATUS_SPLIT = "Split"
    STATUS_CHECK = "CheckUp"
    STATUS_CONVERT = "Convert"
    STATUS_FFMPEG = "FFmpeg"


STATUSES = {
    "ALL": "All",
    "DL": MirrorStatus.STATUS_DOWNLOAD,
    "UP": MirrorStatus.STATUS_UPLOAD,
    "QD": MirrorStatus.STATUS_QUEUEDL,
    "QU": MirrorStatus.STATUS_QUEUEUP,
    "AR": MirrorStatus.STATUS_ARCHIVE,
    "EX": MirrorStatus.STATUS_EXTRACT,
    "SP": MirrorStatus.STATUS_SPLIT,
    "CM": MirrorStatus.STATUS_CONVERT,
    "FF": MirrorStatus.STATUS_FFMPEG,
    "PA": MirrorStatus.STATUS_PAUSED,
    "CK": MirrorStatus.STATUS_CHECK,
}


def get_readable_file_size(size_in_bytes: float) -> str:
    if not size_in_bytes or size_in_bytes < 0:
        return "0B"
    index = 0
    size = float(size_in_bytes)
    while size >= 1024.0 and index < len(SIZE_UNITS) - 1:
        size /= 1024.0
        index += 1
    return f"{size:.2f}{SIZE_UNITS[index]}"


def get_readable_time(seconds: float) -> str:
    seconds = int(seconds)
    if seconds <= 0:
        return "0s"
    periods = [("d", 86400), ("h", 3600), ("m", 60), ("s", 1)]
    result = ""
    for period_name, period_seconds in periods:
        if seconds >= period_seconds:
            period_value, seconds = divmod(seconds, period_seconds)
            result += f"{int(period_value)}{period_name}"
    return result or "0s"


def speed_string_to_bytes(size_text: str) -> float:
    if not size_text:
        return 0.0
    size_text = str(size_text).lower().strip()
    try:
        if "k" in size_text:
            return float(size_text.split("k")[0].strip()) * 1024.0
        elif "m" in size_text:
            return float(size_text.split("m")[0].strip()) * 1048576.0
        elif "g" in size_text:
            return float(size_text.split("g")[0].strip()) * 1073741824.0
        elif "t" in size_text:
            return float(size_text.split("t")[0].strip()) * 1099511627776.0
        elif "b" in size_text:
            return float(size_text.split("b")[0].strip())
        return float(size_text)
    except Exception:
        return 0.0


def get_progress_bar_string(pct: float) -> str:
    p = min(max(pct, 0.0), 100.0)
    cFull = int(p // 8.33)  # 12 blocks total
    p_str = "■" * cFull
    p_str += "□" * (12 - cFull)
    return f"[{p_str}]"


class TaskStatusAdapter:
    """Unified status wrapper over active JobState and DB Job models."""

    def __init__(self, job: Any, job_state: Any | None = None) -> None:
        self.job = job
        self.job_state = job_state
        self.user_id = getattr(job, "chat_id", 0)

    def gid(self) -> str:
        return str(getattr(self.job, "id", ""))

    def name(self) -> str:
        if self.job_state:
            if getattr(self.job_state, "current_download_file", None):
                return Path(self.job_state.current_download_file).name
            if getattr(self.job_state, "current_upload_file", None):
                return Path(self.job_state.current_upload_file).name
            if getattr(self.job_state, "conversion_file", None):
                return Path(self.job_state.conversion_file).name

        url = getattr(self.job, "url", "")
        if url.startswith("[") and url.endswith("]"):
            try:
                parsed = json.loads(url)
                if parsed and isinstance(parsed, list):
                    url = parsed[0]
            except Exception:
                pass
        if url.startswith("torrent:"):
            return Path(url[len("torrent:"):]).name
        if url.startswith("unzip:"):
            return url[len("unzip:"):]
        if len(url) > 40:
            return url[:37] + "..."
        return url or f"Job #{self.gid()}"

    def status(self) -> str:
        if not self.job_state:
            st = getattr(self.job, "status", "queued").lower()
            if st == "waiting":
                return MirrorStatus.STATUS_PAUSED
            return MirrorStatus.STATUS_QUEUEDL

        if getattr(self.job_state, "is_archiving", False):
            return MirrorStatus.STATUS_ARCHIVE
        if getattr(self.job_state, "is_converting", False):
            return MirrorStatus.STATUS_CONVERT

        st = getattr(self.job, "status", "downloading").lower()
        if st == "uploading" or self.job_state.sent > 0 or self.job_state.current_upload_file:
            return MirrorStatus.STATUS_UPLOAD
        if st == "queued":
            return MirrorStatus.STATUS_QUEUEDL
        if st == "waiting":
            return MirrorStatus.STATUS_PAUSED
        return MirrorStatus.STATUS_DOWNLOAD

    def progress(self) -> str:
        if self.job_state:
            if self.status() == MirrorStatus.STATUS_UPLOAD:
                pct = getattr(self.job_state, "current_upload_pct", 0.0)
                return f"{pct:.1f}%"
            else:
                pct = getattr(self.job_state, "download_pct", 0.0)
                return f"{pct:.1f}%"
        return "0.0%"

    def processed_bytes(self) -> str:
        if self.job_state:
            if self.status() == MirrorStatus.STATUS_UPLOAD:
                sent = getattr(self.job_state, "sent", 0)
                total = getattr(self.job, "total_files", 0)
                return f"{sent}/{total if total > 0 else '?'}"
            else:
                downloaded = getattr(self.job_state, "total_downloaded_bytes", 0)
                return get_readable_file_size(downloaded)
        return "0B"

    def size(self) -> str:
        total = getattr(self.job, "total_bytes", 0) or 0
        if total > 0:
            return get_readable_file_size(total)
        return "Calculating"

    def speed(self) -> str:
        if self.job_state:
            if self.status() == MirrorStatus.STATUS_UPLOAD:
                spd = getattr(self.job_state, "upload_speed", 0.0)
                return f"{get_readable_file_size(spd)}/s"
            else:
                spd = getattr(self.job_state, "download_speed", 0.0)
                return f"{get_readable_file_size(spd)}/s"
        return "0B/s"

    def raw_speed(self) -> float:
        if self.job_state:
            if self.status() == MirrorStatus.STATUS_UPLOAD:
                return float(getattr(self.job_state, "upload_speed", 0.0))
            else:
                return float(getattr(self.job_state, "download_speed", 0.0))
        return 0.0

    def eta(self) -> str:
        if not self.job_state:
            return "-"
        spd = self.raw_speed()
        if spd <= 0:
            return "-"
        total = getattr(self.job, "total_bytes", 0) or 0
        if self.status() == MirrorStatus.STATUS_DOWNLOAD:
            downloaded = getattr(self.job_state, "total_downloaded_bytes", 0)
            rem = max(0, total - downloaded)
            if rem > 0 and spd > 0:
                return get_readable_time(rem / spd)
        return "-"


async def get_all_active_task_adapters() -> list[TaskStatusAdapter]:
    """Gather all active, queued, and waiting tasks from queue_manager and DB store."""
    from ...manager.core import queue_manager, store

    tasks: list[TaskStatusAdapter] = []
    active_ids = set()

    # Active running tasks in queue manager
    for job_id, job_state in list(queue_manager.active_jobs.items()):
        job = await store.get_job(job_id)
        if job:
            tasks.append(TaskStatusAdapter(job, job_state))
            active_ids.add(str(job_id))

    # Queued jobs
    queued = await store.queued_jobs()
    for q_job in queued:
        if str(q_job.id) not in active_ids:
            tasks.append(TaskStatusAdapter(q_job, None))
            active_ids.add(str(q_job.id))

    # Waiting (split prompt choice) jobs
    cur = await store.db.execute("SELECT * FROM jobs WHERE status = 'waiting' ORDER BY created_at")
    waiting_rows = await cur.fetchall()
    for r in waiting_rows:
        w_job = store._row_to_job(r)
        if str(w_job.id) not in active_ids:
            tasks.append(TaskStatusAdapter(w_job, None))
            active_ids.add(str(w_job.id))

    return tasks


async def get_task_by_gid(gid: str) -> TaskStatusAdapter | None:
    adapters = await get_all_active_task_adapters()
    for tk in adapters:
        if tk.gid() == gid:
            return tk
    return None


async def get_specific_tasks(status_filter: str, user_id: int | None = None) -> list[TaskStatusAdapter]:
    all_tasks = await get_all_active_task_adapters()
    if user_id:
        all_tasks = [tk for tk in all_tasks if tk.user_id == user_id]

    if status_filter == "All":
        return all_tasks

    result = []
    for tk in all_tasks:
        st = tk.status()
        if st == status_filter or status_filter == MirrorStatus.STATUS_DOWNLOAD and st not in STATUSES.values():
            result.append(tk)
    return result


async def get_readable_message(
    sid: int,
    is_user: bool = False,
    page_no: int = 1,
    status: str = "All",
    page_step: int = 1,
) -> tuple[str | None, Any | None]:
    tasks = await get_specific_tasks(status, sid if is_user else None)
    STATUS_LIMIT = 8
    tasks_no = len(tasks)

    if tasks_no == 0:
        if status == "All":
            return None, None
        else:
            msg = f"<b>No Active {status} Tasks!</b>\n\n"
            buttons = ButtonMaker()
            if not is_user:
                buttons.data_button("OV", f"status {sid} ov", position="header")
            buttons.data_button("Ref", f"status {sid} ref", position="header")
            for label, status_value in list(STATUSES.items()):
                if status_value != status:
                    buttons.data_button(label, f"status {sid} st {status_value}")
            msg += f"<b>CPU:</b> {cpu_percent()}% | <b>FREE:</b> {get_readable_file_size(disk_usage('/').free)}\n"
            msg += f"<b>RAM:</b> {virtual_memory().percent}% | <b>UPTIME:</b> {get_readable_time(time.time() - BOT_START_TIME)}"
            return msg, buttons.build_menu(8)

    pages = (max(tasks_no, 1) + STATUS_LIMIT - 1) // STATUS_LIMIT
    if page_no > pages:
        page_no = (page_no - 1) % pages + 1
    elif page_no < 1:
        page_no = pages - (abs(page_no) % pages)
    start_position = (page_no - 1) * STATUS_LIMIT

    msg = ""
    task_gids: list[tuple[int, str]] = []

    for index, task in enumerate(
        tasks[start_position : STATUS_LIMIT + start_position], start=1
    ):
        tstatus = task.status()
        msg += f"<b>{index + start_position}. {tstatus}: </b><code>{escape(task.name())}</code>"
        
        if tstatus not in [MirrorStatus.STATUS_QUEUEUP, MirrorStatus.STATUS_QUEUEDL, MirrorStatus.STATUS_PAUSED]:
            pct_str = task.progress()
            try:
                pct_val = float(pct_str.strip("%"))
            except Exception:
                pct_val = 0.0
            msg += f"\n{get_progress_bar_string(pct_val)} {pct_str}"
            msg += f"\n<b>Processed:</b> {task.processed_bytes()}"
            msg += f"\n<b>Size:</b> {task.size()}"
            msg += f"\n<b>Speed:</b> {task.speed()}"
            msg += f"\n<b>ETA:</b> {task.eta()}"
        else:
            msg += f"\n<b>Size:</b> {task.size()}"

        msg += f"\n<b>Gid:</b> <code>{task.gid()}</code>\n\n"
        task_gids.append((index + start_position, task.gid()))

    buttons = ButtonMaker()
    if not is_user:
        buttons.data_button("OV", f"status {sid} ov", position="header")

    if tasks_no > STATUS_LIMIT:
        msg += f"<b>Page:</b> {page_no}/{pages} | <b>Tasks:</b> {tasks_no} | <b>Step:</b> {page_step}\n"
        buttons.data_button("<<", f"status {sid} pre", position="header")
        buttons.data_button(">>", f"status {sid} nex", position="header")
        if tasks_no > 30:
            for i in [1, 2, 4, 6, 8, 10, 15]:
                buttons.data_button(str(i), f"status {sid} ps {i}", position="footer")

    if status != "All" or tasks_no > 8:
        for label, status_value in list(STATUSES.items()):
            if status_value != status:
                buttons.data_button(label, f"status {sid} st {status_value}")

    buttons.data_button("Ref", f"status {sid} ref", position="header")
    button_markup = buttons.build_menu(8)

    if task_gids:
        from pyrogram.types import InlineKeyboardButton
        cancel_buttons = [
            InlineKeyboardButton(
                text=f"X {num}",
                callback_data=f"status {sid} cancel {gid}",
            )
            for num, gid in task_gids
        ]
        if button_markup is None:
            from pyrogram.types import InlineKeyboardMarkup
            button_markup = InlineKeyboardMarkup([])

        for i in range(0, len(cancel_buttons), 4):
            button_markup.inline_keyboard.append(cancel_buttons[i : i + 4])

    msg += f"<b>CPU:</b> {cpu_percent()}% | <b>FREE:</b> {get_readable_file_size(disk_usage('/').free)}\n"
    msg += f"<b>RAM:</b> {virtual_memory().percent}% | <b>UPTIME:</b> {get_readable_time(time.time() - BOT_START_TIME)}"

    return msg, button_markup
