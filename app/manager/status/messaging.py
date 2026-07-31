from __future__ import annotations

import asyncio
import logging

from pyrogram import Client
from pyrogram.types import LinkPreviewOptions, Message

from ...rate_limiter import telegram_limiter
from ...telegram_helper.message_utils import (
    send_message as helper_send_message,
)

log = logging.getLogger(__name__)


def format_size(size_bytes: float) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"


def make_progress_bar(pct: float) -> str:
    filled = max(0, min(10, int(round(pct / 10))))
    return "●" * filled + "○" * (10 - filled)

async def safe_send(client: Client, chat_id: int, text: str, **kwargs) -> Message | None:
    res = await helper_send_message(client, text, chat_id=chat_id, buttons=kwargs.get("reply_markup"))
    if isinstance(res, Message):
        return res
    return None


_last_edit_times: dict[tuple[int, int], float] = {}


async def safe_edit(client: Client, chat_id: int, message_id: int, text: str, reply_markup=None, force: bool = False) -> bool:
    import time

    from pyrogram.errors import FloodWait, MessageNotModified

    now = time.time()
    key = (chat_id, message_id)
    if not force:
        last_t = _last_edit_times.get(key, 0.0)
        if now - last_t < 10.0:
            return False

    await telegram_limiter.acquire(chat_id)
    try:
        await client.edit_message_text(
            chat_id,
            message_id,
            text,
            reply_markup=reply_markup,
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        _last_edit_times[key] = time.time()
        return True
    except MessageNotModified:
        _last_edit_times[key] = time.time()
        return True
    except FloodWait as e:
        telegram_limiter.notify_floodwait(e.value, chat_id)
        log.warning("Telegram FloodWait: waiting %s seconds on status edit", e.value)
        await asyncio.sleep(e.value + 1)
        if force:
            try:
                await client.edit_message_text(
                    chat_id,
                    message_id,
                    text,
                    reply_markup=reply_markup,
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )
                _last_edit_times[key] = time.time()
                return True
            except Exception as ex:
                log.warning("Failed forced retry edit of status message %s: %s", message_id, ex)
        return False
    except Exception as e:
        log.warning("Failed to edit status message %s in chat %s: %s", message_id, chat_id, e)
        return False


async def safe_delete(client: Client, chat_id: int, message_id: int) -> bool:
    from pyrogram.errors import FloodWait
    await telegram_limiter.acquire(chat_id)
    try:
        await client.delete_messages(chat_id, message_id)
        return True
    except FloodWait as e:
        telegram_limiter.notify_floodwait(e.value, chat_id)
        log.warning("Telegram FloodWait: waiting %s seconds on message delete", e.value)
        await asyncio.sleep(e.value + 1)
        return False
    except Exception as e:
        log.warning("Failed to delete message %s in chat %s: %s", message_id, chat_id, e)
        return False


async def safe_pin(client: Client, chat_id: int, message_id: int, disable_notification: bool = True) -> bool:
    from pyrogram.errors import FloodWait
    from pyrogram.types import Message as PyrogramMessage
    await telegram_limiter.acquire(chat_id)
    try:
        res = await client.pin_chat_message(chat_id, message_id, disable_notification=disable_notification, both_sides=True)
        if isinstance(res, PyrogramMessage):
            try:
                await res.delete()
            except Exception:
                pass
        return True
    except FloodWait as e:
        telegram_limiter.notify_floodwait(e.value, chat_id)
        log.warning("Telegram FloodWait: waiting %s seconds on pin_chat_message", e.value)
        await asyncio.sleep(e.value + 1)
        return False
    except Exception:
        try:
            res = await client.pin_chat_message(chat_id, message_id, disable_notification=disable_notification)
            if isinstance(res, PyrogramMessage):
                try:
                    await res.delete()
                except Exception:
                    pass
            return True
        except Exception as ex:
            log.warning("Failed to pin status message %s in chat %s: %s", message_id, chat_id, ex)
            return False
