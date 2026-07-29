from __future__ import annotations

import asyncio
import logging
import re
import time
from html import escape
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple, Union

from pyrogram import Client
from pyrogram.errors import FloodWait, FloodPremiumWait, RPCError, BadRequest
from pyrogram.types import (
    InputMediaPhoto,
    InputMediaDocument,
    Message,
)
from tenacity import (
    retry,
    wait_exponential,
    stop_after_attempt,
    retry_if_exception_type,
)

from ...config import settings
from ...rate_limiter import telegram_limiter
from ...conversion import convert_image_to_png_async
from ..video import probe_video, extract_video_thumbnail, take_screenshots
import av

log = logging.getLogger(__name__)

IMAGE_EXT = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif",
    ".bmp", ".tiff", ".heic", ".heif", ".ico"
}
VIDEO_EXT = {
    ".mp4", ".mov", ".webm", ".mkv", ".avi", ".flv", ".wmv",
    ".3gp", ".mpeg", ".mpg", ".m4v", ".ts", ".f4v"
}
AUDIO_EXT = {
    ".mp3", ".flac", ".m4a", ".aac", ".opus", ".ogg", ".wav",
    ".wma", ".alac", ".aiff"
}
CONVERTIBLE_IMAGE_EXT = {".webp", ".bmp", ".tiff", ".heic", ".heif", ".ico"}

_upload_semaphore = asyncio.Semaphore(1)


class UploadTooLarge(Exception):
    pass


def natural_sort_key(s: str) -> list[Union[int, str]]:
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', str(s))]


def probe_audio(audio_path: Path) -> dict[str, Any]:
    info = {"duration": 0, "artist": "", "title": ""}
    try:
        with av.open(str(audio_path)) as container:
            if container.duration:
                info["duration"] = int(round(container.duration / 1000000.0))
            meta = container.metadata or {}
            info["artist"] = meta.get("artist") or meta.get("ARTIST") or ""
            info["title"] = meta.get("title") or meta.get("TITLE") or audio_path.stem
    except Exception as e:
        log.warning("PyAV failed to probe audio %s: %s", audio_path.name, e)
    return info


def is_photo_invalid_for_telegram(file_path: Path) -> bool:
    try:
        import PIL.Image
        with PIL.Image.open(file_path) as img:
            if img.mode in ("CMYK", "P", "1"):
                return True
            w, h = img.size
            if w <= 0 or h <= 0:
                return True
            if w + h > 10000 or max(w, h) > 9900:
                return True
            ratio = w / h if h > 0 else 0.0
            if ratio > 15.0 or ratio < (1.0 / 15.0):
                return True
    except Exception:
        return True
    return False


class TelegramUploader:
    """Stateful Telegram uploader module inspired by mirror-leech-telegram-bot's telegram_uploader.py."""

    def __init__(
        self,
        client: Client,
        chat_id: int,
        path: Path,
        progress: Optional[Callable[[int, int], Coroutine[None, None, None]]] = None,
        lprefix: str = "",
        as_doc: bool = False,
        media_group: bool = True,
    ) -> None:
        self.client = client
        self.chat_id = chat_id
        self.path = path
        self.progress = progress
        self.lprefix = lprefix
        self.as_doc = as_doc
        self.media_group = media_group

        self.last_uploaded = 0
        self.processed_bytes = 0
        self.start_time = time.time()
        self.total_files = 0
        self.corrupted = 0
        self.is_cancelled = False
        self.sent_msg: Optional[Message] = None

    async def _upload_progress_callback(self, current: int, total: int) -> None:
        if self.is_cancelled:
            try:
                self.client.stop_transmission()
            except Exception:
                pass
        chunk_size = current - self.last_uploaded
        self.last_uploaded = current
        self.processed_bytes += chunk_size

        if self.progress:
            try:
                await self.progress(current, total)
            except Exception as e:
                log.debug("Progress callback error: %s", e)

    def _prepare_filename_and_caption(self, file_path: Path) -> Tuple[str, Path]:
        filename = file_path.name

        # Check for split part pattern like _part001.mp4, .part001.mp4, .001
        part_match = re.search(r'((?:_part|\.part)\d+\.[^.]+$|\.\d+$)', filename, re.IGNORECASE)
        if part_match:
            part_suffix = part_match.group(1)
            base_stem = filename[:-len(part_suffix)]
        else:
            part_suffix = file_path.suffix
            base_stem = file_path.stem

        display_name = filename
        if len(filename) > 60:
            remain = max(10, 60 - len(part_suffix))
            display_name = f"{base_stem[:remain]}{part_suffix}"

        if self.lprefix:
            cap_mono = f"{self.lprefix} <code>{escape(display_name)}</code>"
        else:
            cap_mono = f"<code>{escape(display_name)}</code>"

        return cap_mono, file_path

    async def upload(self) -> None:
        """Main upload executor supporting single file or directory of files."""
        if not self.path.exists():
            log.error("Upload path %s does not exist", self.path)
            return

        files_to_upload: List[Path] = []
        if self.path.is_file():
            files_to_upload.append(self.path)
        else:
            for p in self.path.rglob("*"):
                if p.is_file() and not p.name.startswith("."):
                    files_to_upload.append(p)

        files_to_upload.sort(key=lambda x: natural_sort_key(x.name))
        self.total_files = len(files_to_upload)

        if self.total_files == 0:
            log.warning("No files found to upload in %s", self.path)
            return

        split_groups: Dict[str, List[Path]] = {}
        single_files: List[Path] = []

        if self.media_group:
            for f in files_to_upload:
                match = re.search(r'(.+?)(?:\.part\d+\.[^.]+$|\.0*\d+$)', f.name, re.IGNORECASE)
                if match:
                    group_key = match.group(1)
                    if group_key not in split_groups:
                        split_groups[group_key] = []
                    split_groups[group_key].append(f)
                else:
                    single_files.append(f)
        else:
            single_files = files_to_upload

        async with _upload_semaphore:
            for group_key, group_files in split_groups.items():
                if self.is_cancelled:
                    return
                if len(group_files) > 1:
                    log.info("Uploading %s split parts as media group for %s", len(group_files), group_key)
                    await self._upload_media_group_batch(group_files)
                else:
                    single_files.extend(group_files)

            single_files.sort(key=lambda x: natural_sort_key(x.name))
            for f in single_files:
                if self.is_cancelled:
                    return
                self.last_uploaded = 0
                await self._upload_single_file_with_retry(f)
                await asyncio.sleep(1.0)

    async def _upload_media_group_batch(self, group_files: List[Path]) -> None:
        """Batch upload up to 10 split files in a media group."""
        for i in range(0, len(group_files), 10):
            if self.is_cancelled:
                return
            batch = group_files[i : i + 10]
            media_list: List[InputMediaDocument] = []
            for f in batch:
                cap_mono, f_renamed = self._prepare_filename_and_caption(f)
                media_list.append(InputMediaDocument(media=str(f_renamed), caption=cap_mono))

            await telegram_limiter.acquire_upload(self.chat_id)
            try:
                await self.client.send_media_group(self.chat_id, media=media_list)
                log.info("Successfully uploaded media group batch of %s files", len(batch))
            except (FloodWait, FloodPremiumWait) as e:
                telegram_limiter.notify_floodwait(e.value, self.chat_id)
                log.warning("FloodWait %ss on send_media_group", e.value)
                await asyncio.sleep(e.value + 2.0)
                await self.client.send_media_group(self.chat_id, media=media_list)
            except Exception as e:
                log.warning("Media group upload failed (%s). Falling back to single file uploads.", e)
                for f in batch:
                    await self._upload_single_file_with_retry(f)

    async def _upload_single_file_with_retry(self, file_path: Path) -> None:
        cap_mono, file_path = self._prepare_filename_and_caption(file_path)

        size = file_path.stat().st_size
        if size == 0:
            log.warning("%s size is 0 bytes, skipping", file_path.name)
            self.corrupted += 1
            return
        if size > settings.max_upload_bytes:
            raise UploadTooLarge(f"{file_path.name} is {size / 1e9:.2f}GB, exceeds MTProto limit")

        ext = file_path.suffix.lower()
        converted_png: Optional[Path] = None
        if ext in CONVERTIBLE_IMAGE_EXT:
            png_path = file_path.with_suffix(".png")
            if await convert_image_to_png_async(file_path, png_path):
                converted_png = png_path
                file_path = png_path
                ext = ".png"

        try:
            await self._upload_file(cap_mono, file_path, force_document=self.as_doc)
        except Exception as e:
            log.error("Failed to upload %s: %s", file_path.name, e)
            self.corrupted += 1
        finally:
            if converted_png and converted_png.exists():
                try:
                    converted_png.unlink()
                except Exception:
                    pass

    @retry(
        wait=wait_exponential(multiplier=2, min=4, max=10),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(RPCError),
    )
    async def _upload_file(
        self,
        cap_mono: str,
        file_path: Path,
        force_document: bool = False,
    ) -> None:
        if self.is_cancelled:
            return

        ext = file_path.suffix.lower()
        is_video = ext in VIDEO_EXT
        is_audio = ext in AUDIO_EXT
        is_image = ext in IMAGE_EXT and ext not in CONVERTIBLE_IMAGE_EXT

        if is_image and not force_document and is_photo_invalid_for_telegram(file_path):
            log.info("Image %s has dimensions/color space unsuited for Telegram photo API; uploading as document", file_path.name)
            force_document = True

        thumb_path: Optional[Path] = None
        screenshots: List[Path] = []
        video_meta: Dict[str, Any] = {}

        await telegram_limiter.acquire_upload(self.chat_id)

        try:
            if force_document or (not is_video and not is_audio and not is_image):
                if is_video:
                    thumb_path = await extract_video_thumbnail(file_path)

                kwargs = {
                    "caption": cap_mono,
                    "force_document": True,
                    "disable_notification": True,
                    "progress": self._upload_progress_callback,
                }
                if thumb_path:
                    kwargs["thumb"] = str(thumb_path)

                self.sent_msg = await self.client.send_document(self.chat_id, str(file_path), **kwargs)

            elif is_video:
                video_meta = await probe_video(file_path)
                duration = video_meta.get("duration", 0)
                thumb_path = await extract_video_thumbnail(file_path)

                if duration >= 60:
                    screenshots = await take_screenshots(file_path, duration)

                kwargs = {
                    "caption": cap_mono,
                    "duration": duration,
                    "supports_streaming": True,
                    "disable_notification": True,
                    "progress": self._upload_progress_callback,
                }
                if "width" in video_meta:
                    kwargs["width"] = video_meta["width"]
                if "height" in video_meta:
                    kwargs["height"] = video_meta["height"]
                if thumb_path:
                    kwargs["thumb"] = str(thumb_path)

                self.sent_msg = await self.client.send_video(self.chat_id, str(file_path), **kwargs)

                if screenshots:
                    await self._send_screenshots(screenshots, file_path.name)

            elif is_audio:
                audio_meta = probe_audio(file_path)
                kwargs = {
                    "caption": cap_mono,
                    "duration": audio_meta.get("duration", 0),
                    "performer": audio_meta.get("artist", ""),
                    "title": audio_meta.get("title", file_path.stem),
                    "disable_notification": True,
                    "progress": self._upload_progress_callback,
                }
                self.sent_msg = await self.client.send_audio(self.chat_id, str(file_path), **kwargs)

            else:  # photo
                kwargs = {
                    "caption": cap_mono,
                    "disable_notification": True,
                    "progress": self._upload_progress_callback,
                }
                self.sent_msg = await self.client.send_photo(self.chat_id, str(file_path), **kwargs)

        except (FloodWait, FloodPremiumWait) as f:
            telegram_limiter.notify_floodwait(f.value, self.chat_id)
            log.warning("Telegram FloodWait on upload: waiting %s seconds", f.value)
            await asyncio.sleep(f.value * 2.0)
            return await self._upload_file(cap_mono, file_path, force_document)
        except BadRequest as err:
            err_msg = str(err)
            log.warning("BadRequest during upload of %s: %s", file_path.name, err_msg)
            if not force_document:
                if any(x in err_msg for x in ("PHOTO_SAVE_FILE_INVALID", "PHOTO_INVALID_DIMENSIONS", "MEDIA_INVALID")):
                    log.info("Photo format invalid for Telegram photo API (%s). Enabling document upload mode for remaining files in batch.", err_msg)
                    self.as_doc = True
                else:
                    log.info("Retrying %s as document...", file_path.name)
                self.last_uploaded = 0
                return await self._upload_file(cap_mono, file_path, force_document=True)
            raise err
        finally:
            if thumb_path and thumb_path.exists():
                try:
                    thumb_path.unlink()
                except Exception:
                    pass
            for shot in screenshots:
                if shot.exists():
                    try:
                        shot.unlink()
                    except Exception:
                        pass

    async def _send_screenshots(self, screenshots: List[Path], video_name: str) -> None:
        try:
            log.info("Sending %s screenshots grouped for %s", len(screenshots), video_name)
            media = [InputMediaPhoto(str(shot)) for shot in screenshots]
            media[0].caption = f"Screenshots for <code>{escape(video_name)}</code>"
            await telegram_limiter.acquire(self.chat_id)
            await self.client.send_media_group(self.chat_id, media=media)
        except Exception as e:
            log.warning("Failed to send screenshots for %s: %s", video_name, e)

    @property
    def speed(self) -> float:
        elapsed = time.time() - self.start_time
        if elapsed > 0:
            return self.processed_bytes / elapsed
        return 0.0


async def upload_file(
    client: Client,
    chat_id: int,
    path: Path,
    progress: Optional[Callable[[int, int], Coroutine[None, None, None]]] = None,
    lprefix: str = "",
    as_doc: bool = False,
    media_group: bool = True,
) -> None:
    """Uploads a file or directory using the stateful TelegramUploader module."""
    uploader = TelegramUploader(
        client=client,
        chat_id=chat_id,
        path=path,
        progress=progress,
        lprefix=lprefix,
        as_doc=as_doc,
        media_group=media_group,
    )
    await uploader.upload()
