from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from pyrogram import Client
from pyrogram.errors import FloodWait, MessageNotModified
from pyrogram.types import InlineKeyboardMarkup, LinkPreviewOptions, Message

from ..rate_limiter import telegram_limiter

log = logging.getLogger(__name__)

# Global status tracking structures
task_dict_lock = asyncio.Lock()
status_dict: dict[int, dict[str, Any]] = {}
intervals: dict[str, Any] = {"status": {}, "stopAll": False}


async def send_message(
    target: Client | Message,
    text: str,
    buttons: InlineKeyboardMarkup | None = None,
    chat_id: int | None = None,
    block: bool = True,
) -> Message | str | None:
    """Sends a Telegram message with rate limiting and FloodWait protection."""
    cid = chat_id or (target.chat.id if isinstance(target, Message) else None)
    if cid:
        await telegram_limiter.acquire(cid)

    try:
        if isinstance(target, Message):
            return await target.reply(
                text=text,
                disable_notification=True,
                reply_markup=buttons,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
        elif isinstance(target, Client) and chat_id is not None:
            return await target.send_message(
                chat_id=chat_id,
                text=text,
                disable_notification=True,
                reply_markup=buttons,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
        else:
            log.error("send_message failed: invalid target or missing chat_id")
            return None
    except FloodWait as f:
        telegram_limiter.notify_floodwait(f.value, cid)
        log.warning("Telegram FloodWait on send_message: waiting %s seconds", f.value)
        if not block:
            return f"Telegram FloodWait: {f.value}s"
        await asyncio.sleep(f.value + 1)
        return await send_message(target, text, buttons, chat_id, block)
    except Exception as e:
        log.error("Error in send_message: %s", e)
        return str(e)


async def edit_message(
    message: Message,
    text: str,
    buttons: InlineKeyboardMarkup | None = None,
    block: bool = True,
) -> Message | bool | str:
    """Edits a Telegram message with rate limiting and FloodWait protection."""
    cid = message.chat.id if message and message.chat else None
    if cid:
        await telegram_limiter.acquire(cid)

    try:
        res = await message.edit_text(
            text=text,
            reply_markup=buttons,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        return res
    except MessageNotModified:
        return True
    except FloodWait as f:
        telegram_limiter.notify_floodwait(f.value, cid)
        log.warning("Telegram FloodWait on edit_message: waiting %s seconds", f.value)
        if not block:
            return f"Telegram FloodWait: {f.value}s"
        await asyncio.sleep(f.value + 1)
        return await edit_message(message, text, buttons, block)
    except Exception as e:
        log.error("Error in edit_message: %s", e)
        return str(e)


async def delete_message(message: Message | None) -> bool:
    """Safely deletes a Telegram message."""
    if not message:
        return False
    cid = message.chat.id if message.chat else None
    if cid:
        await telegram_limiter.acquire(cid)

    try:
        await message.delete()
        return True
    except FloodWait as f:
        telegram_limiter.notify_floodwait(f.value, cid)
        log.warning("Telegram FloodWait on delete_message: waiting %s seconds", f.value)
        await asyncio.sleep(f.value + 1)
        return await delete_message(message)
    except Exception as e:
        log.error("Failed to delete message: %s", e)
        return False


async def auto_delete_message(
    cmd_message: Message | None = None,
    bot_message: Message | None = None,
    delay: int = 60,
) -> None:
    """Schedules automatic deletion of messages after a delay."""
    await asyncio.sleep(delay)
    if cmd_message:
        await delete_message(cmd_message)
    if bot_message:
        await delete_message(bot_message)


async def delete_status() -> None:
    """Deletes all active status messages and cleans up status tracking dict."""
    async with task_dict_lock:
        for key, data in list(status_dict.items()):
            try:
                await delete_message(data.get("message"))
                del status_dict[key]
            except Exception as e:
                log.error("Error deleting status message for key %s: %s", key, e)
        for sid, task in list(intervals["status"].items()):
            if task and not task.done():
                task.cancel()
            del intervals["status"][sid]


async def update_status_message(sid: int, force: bool = False) -> None:
    """Updates the status message for a given chat or user key `sid`."""
    if intervals.get("stopAll"):
        return

    from ..manager.status.status_utils import get_readable_message

    async with task_dict_lock:
        if sid not in status_dict:
            if obj := intervals["status"].get(sid):
                if not obj.done():
                    obj.cancel()
                del intervals["status"][sid]
            return

        if not force and time.time() - status_dict[sid].get("time", 0.0) < 3.0:
            return

        status_dict[sid]["time"] = time.time()
        page_no = status_dict[sid].get("page_no", 1)
        status_filter = status_dict[sid].get("status", "All")
        is_user = status_dict[sid].get("is_user", False)
        page_step = status_dict[sid].get("page_step", 1)

        text, buttons = await get_readable_message(
            sid, is_user, page_no, status_filter, page_step
        )

        if text is None:
            del status_dict[sid]
            if obj := intervals["status"].get(sid):
                if not obj.done():
                    obj.cancel()
                del intervals["status"][sid]
            return

        current_msg = status_dict[sid].get("message")
        if not current_msg:
            return

        if text != getattr(current_msg, "text", ""):
            res = await edit_message(current_msg, text, buttons, block=False)
            if isinstance(res, str):
                if "400" in res or "404" in res or "message to edit not found" in res.lower():
                    del status_dict[sid]
                    if obj := intervals["status"].get(sid):
                        if not obj.done():
                            obj.cancel()
                        del intervals["status"][sid]
                else:
                    log.error("Status message edit failed for sid %s: %s", sid, res)
                return
            status_dict[sid]["time"] = time.time()


async def _status_loop(sid: int) -> None:
    """Background task loop to update status periodically."""
    try:
        while True:
            await asyncio.sleep(3.0)
            async with task_dict_lock:
                if sid not in status_dict:
                    break
            await update_status_message(sid)
    except asyncio.CancelledError:
        pass


async def send_status_message(target_msg: Message, user_id: int = 0) -> None:
    """Sends or replaces the active status message for chat or user."""
    if intervals.get("stopAll"):
        return

    from ..manager.status.status_utils import get_readable_message

    sid = user_id or target_msg.chat.id
    is_user = bool(user_id)

    async with task_dict_lock:
        if sid in status_dict:
            page_no = status_dict[sid].get("page_no", 1)
            status_filter = status_dict[sid].get("status", "All")
            page_step = status_dict[sid].get("page_step", 1)

            text, buttons = await get_readable_message(
                sid, is_user, page_no, status_filter, page_step
            )

            if text is None:
                del status_dict[sid]
                if obj := intervals["status"].get(sid):
                    if not obj.done():
                        obj.cancel()
                    del intervals["status"][sid]
                return

            old_message = status_dict[sid].get("message")
            new_msg = await send_message(target_msg, text, buttons, block=False)
            if isinstance(new_msg, str) or not isinstance(new_msg, Message):
                log.error("Failed to send new status message for sid %s: %s", sid, new_msg)
                return

            if old_message:
                asyncio.create_task(delete_message(old_message))

            status_dict[sid].update({
                "message": new_msg,
                "time": time.time(),
            })
        else:
            text, buttons = await get_readable_message(sid, is_user)
            if text is None:
                from ..manager.status.status_utils import (
                    get_readable_file_size,
                    get_readable_time,
                    get_system_stats_snapshot,
                )

                stats = get_system_stats_snapshot()
                currentTime = get_readable_time(stats["uptime_seconds"])
                free = get_readable_file_size(stats["disk_free_bytes"])
                net_sent = get_readable_file_size(stats["net_sent_bytes_since_start"])
                net_recv = get_readable_file_size(stats["net_recv_bytes_since_start"])
                idle_text = (
                    "No Active Tasks!\n"
                    f"CPU: {stats['cpu_percent']}% | FREE: {free}\n"
                    f"RAM: {stats['ram_percent']}% | SERVER UPTIME: {currentTime}\n"
                    f"NET I/O: ↑ {net_sent} | ↓ {net_recv}"
                )
                reply_msg = await send_message(target_msg, idle_text)
                if isinstance(reply_msg, Message):
                    asyncio.create_task(auto_delete_message(target_msg, reply_msg, delay=60))
                return

            new_msg = await send_message(target_msg, text, buttons, block=False)
            if isinstance(new_msg, str) or not isinstance(new_msg, Message):
                log.error("Failed to send status message for sid %s: %s", sid, new_msg)
                return

            status_dict[sid] = {
                "message": new_msg,
                "time": time.time(),
                "page_no": 1,
                "page_step": 1,
                "status": "All",
                "is_user": is_user,
            }

            if sid not in intervals["status"] or intervals["status"][sid].done():
                task = asyncio.create_task(_status_loop(sid))
                intervals["status"][sid] = task
