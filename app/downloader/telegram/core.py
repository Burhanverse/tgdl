from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Callable, Coroutine, Optional, Set

from pyrogram import Client
from pyrogram.errors import FloodWait, FloodPremiumWait
from pyrogram.types import Message

from ...rate_limiter import telegram_limiter

_global_lock: Optional[asyncio.Lock] = None

def get_global_lock() -> asyncio.Lock:
    global _global_lock
    if _global_lock is None:
        _global_lock = asyncio.Lock()
    return _global_lock

GLOBAL_GID: Set[str] = set()


class TelegramDownloadError(Exception):
    pass


class TelegramDownloader:
    """
    Stateful Telegram media downloader inspired by mirror-leech-telegram-bot's telegram_download.py.
    """

    def __init__(
        self,
        client: Client,
        message: Message,
        dest_dir: Path,
        progress_cb: Optional[Callable[[int, int, str], Coroutine[None, None, None]]] = None,
        custom_file_name: Optional[str] = None,
    ) -> None:
        self.client = client
        self.message = message
        self.dest_dir = dest_dir
        self.progress_cb = progress_cb
        self.custom_file_name = custom_file_name

        self.processed_bytes = 0
        self.total_bytes = 0
        self.start_time = time.time()
        self.last_time = time.time()
        self.last_bytes = 0
        self.current_speed = 0.0
        self.is_downloading = False
        self.is_cancelled = False
        self.file_unique_id = ""
        self.downloaded_path: Optional[Path] = None

    @property
    def speed(self) -> float:
        if self.current_speed > 0:
            return self.current_speed
        elapsed = time.time() - self.start_time
        if elapsed > 0:
            return self.processed_bytes / elapsed
        return 0.0

    def cancel(self) -> None:
        self.is_cancelled = True
        try:
            self.client.stop_transmission()
        except Exception:
            pass

    async def _on_download_progress(self, current: int, total: int) -> None:
        if self.is_cancelled:
            try:
                self.client.stop_transmission()
            except Exception:
                pass
        self.processed_bytes = current
        if total > 0:
            self.total_bytes = total

        now = time.time()
        dt = now - self.last_time
        if dt >= 0.5:
            db = current - self.last_bytes
            inst_speed = max(0.0, db / dt)
            if self.last_bytes > 0:
                self.current_speed = 0.7 * inst_speed + 0.3 * self.current_speed
            else:
                self.current_speed = inst_speed
            self.last_time = now
            self.last_bytes = current

        if self.progress_cb:
            file_name = self.custom_file_name or (self.downloaded_path.name if self.downloaded_path else "telegram_media")
            try:
                await self.progress_cb(current, total, self.speed, file_name)
            except TypeError:
                try:
                    await self.progress_cb(current, total, file_name)
                except Exception as e:
                    log.debug("Progress callback error: %s", e)
            except Exception as e:
                log.debug("Progress callback error: %s", e)

    async def download(self) -> Path:
        """Extracts media from Pyrogram Message and downloads it to dest_dir."""
        media = (
            self.message.document
            or self.message.video
            or self.message.audio
            or self.message.photo
            or self.message.voice
            or self.message.video_note
            or self.message.sticker
            or self.message.animation
        )

        if media is None:
            raise TelegramDownloadError("No downloadable media found in the provided Telegram message.")

        self.file_unique_id = getattr(media, "file_unique_id", "")
        if self.file_unique_id:
            async with get_global_lock():
                if self.file_unique_id in GLOBAL_GID:
                    raise TelegramDownloadError(f"File {self.file_unique_id} is already being downloaded.")
                GLOBAL_GID.add(self.file_unique_id)

        try:
            self.total_bytes = getattr(media, "file_size", 0) or 0
            file_name = self.custom_file_name or getattr(media, "file_name", None)

            if not file_name:
                if self.message.photo:
                    file_name = f"photo_{self.message.id}.jpg"
                elif self.message.video:
                    file_name = f"video_{self.message.id}.mp4"
                elif self.message.audio:
                    file_name = f"audio_{self.message.id}.mp3"
                else:
                    file_name = f"file_{self.message.id}.bin"

            self.dest_dir.mkdir(parents=True, exist_ok=True)
            target_path = self.dest_dir / file_name
            self.downloaded_path = target_path

            self.is_downloading = True
            self.start_time = time.time()

            await self._download_with_retry(target_path)

            if self.is_cancelled or not target_path.exists():
                if target_path.exists():
                    target_path.unlink(missing_ok=True)
                raise asyncio.CancelledError("Telegram media download cancelled.")

            return target_path

        finally:
            self.is_downloading = False
            if self.file_unique_id:
                async with get_global_lock():
                    if self.file_unique_id in GLOBAL_GID:
                        GLOBAL_GID.remove(self.file_unique_id)

    async def _download_with_retry(self, target_path: Path) -> None:
        await telegram_limiter.acquire(self.message.chat.id)
        try:
            res = await self.client.download_media(
                message=self.message,
                file_name=str(target_path),
                progress=self._on_download_progress,
            )
            if res is None and not self.is_cancelled:
                raise TelegramDownloadError("Pyrogram download_media returned None.")
        except (FloodWait, FloodPremiumWait) as f:
            telegram_limiter.notify_floodwait(f.value, self.message.chat.id)
            log.warning("Telegram FloodWait on download_media: waiting %s seconds", f.value)
            await asyncio.sleep(f.value + 1)
            return await self._download_with_retry(target_path)
        except Exception as e:
            if self.is_cancelled:
                raise asyncio.CancelledError("Download cancelled.") from e
            raise TelegramDownloadError(f"Failed to download Telegram media: {e}") from e


async def download_telegram_media(
    client: Client,
    message: Message,
    dest_dir: Path,
    progress_cb: Optional[Callable[[int, int, str], Coroutine[None, None, None]]] = None,
    custom_file_name: Optional[str] = None,
) -> Path:
    """Helper function to download media from a Pyrogram message to dest_dir."""
    downloader = TelegramDownloader(
        client=client,
        message=message,
        dest_dir=dest_dir,
        progress_cb=progress_cb,
        custom_file_name=custom_file_name,
    )
    return await downloader.download()
