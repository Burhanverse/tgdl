from __future__ import annotations

import json
import logging
import shutil
import uuid
from pathlib import Path
from pyrogram import Client, filters
from pyrogram.types import Message, LinkPreviewOptions, InlineKeyboardMarkup, InlineKeyboardButton

from ..config import settings
from ..middleware import is_job_owner
from ..manager import queue_manager, store
from ..manager.status.compiler import compile_queued_status_text
from ..uploader import upload_to_pixeldrain

log = logging.getLogger(__name__)


async def _create_and_enqueue_job(chat_id: int, target_url: str, message: Message, display_text: str) -> None:
    job = await store.create_job(chat_id, target_url, split_large_files=1, args=None)
    await store.update_progress(job.id, status="queued")
    await queue_manager.add_job(job.id)

    queued_text = compile_queued_status_text(job.id, display_text, "")
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Cancel", callback_data=f"cancel_job:{job.id}")]
    ])
    status_msg = await message.reply_text(
        queued_text,
        reply_markup=keyboard,
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )
    await store.set_status_message(job.id, status_msg.id)


def register_download_handlers(app: Client) -> None:

    @app.on_message(filters.command(["m", "mirror"]))
    async def mirror_cmd(_, message: Message) -> None:
        target_url = None
        display_text = "Web Mirror"

        # 1. Check if user replied to a Telegram message containing media
        if message.reply_to_message:
            reply_msg = message.reply_to_message
            media = (
                reply_msg.document
                or reply_msg.video
                or reply_msg.audio
                or reply_msg.photo
                or reply_msg.voice
                or reply_msg.video_note
                or reply_msg.sticker
                or reply_msg.animation
            )
            if media:
                target_url = f"mirror_tg:{reply_msg.chat.id}:{reply_msg.id}"
                file_name = getattr(media, "file_name", None) or f"tg_media_{reply_msg.id}"
                display_text = f"Web Mirror: Telegram file `{file_name}`"

        # 2. Check if URL text argument is provided
        if not target_url:
            parts = message.text.split(maxsplit=1)
            if len(parts) >= 2:
                raw_link = parts[1].strip()
                target_url = f"mirror:{raw_link}"
                display_text = f"Web Mirror: {raw_link}"

        if not target_url:
            await message.reply_text("Provide a URL or reply to a Telegram media message with `/m` or `/mirror`.")
            return

        await _create_and_enqueue_job(message.chat.id, target_url, message, display_text)

    @app.on_message(filters.command(["direct", "dl"]))
    async def direct_cmd(_, message: Message) -> None:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            await message.reply_text("Provide a direct file URL: `/direct <url>` or `/dl <url>`.")
            return

        raw_link = parts[1].strip()
        link = f"direct:{raw_link}"
        await _create_and_enqueue_job(message.chat.id, link, message, raw_link)

    @app.on_message(filters.command("gdl"))
    async def gdl_cmd(_, message: Message) -> None:
        if not message.reply_to_message or not message.reply_to_message.document:
            await message.reply_text("Reply to a .txt file containing URLs with `/gdl [options]`.")
            return

        doc = message.reply_to_message.document
        if not (doc.file_name.endswith(".txt") or (doc.mime_type and doc.mime_type.startswith("text/"))):
            await message.reply_text("Please reply to a text (.txt) file.")
            return

        temp_path = await message.reply_to_message.download()
        if not temp_path or not Path(temp_path).exists():
            await message.reply_text("Failed to download the file.")
            return

        try:
            content = Path(temp_path).read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            await message.reply_text(f"Failed to read the file: {e}")
            return
        finally:
            Path(temp_path).unlink(missing_ok=True)

        urls = []
        for line in content.splitlines():
            line = line.strip()
            if line.startswith(("http://", "https://")):
                urls.append(line)

        if not urls:
            await message.reply_text("No valid URLs found in the text file.")
            return

        urls_json = json.dumps(urls)
        await _create_and_enqueue_job(message.chat.id, urls_json, message, urls_json)

    @app.on_message(filters.command("tor"))
    async def tor_cmd(_, message: Message) -> None:
        target_url = None

        if message.reply_to_message and message.reply_to_message.document:
            doc = message.reply_to_message.document
            if doc.file_name.endswith(".torrent") or (doc.mime_type and "torrent" in doc.mime_type):
                temp_path = await message.reply_to_message.download()
                if temp_path:
                    torrents_dir = settings.data_dir / "torrents"
                    torrents_dir.mkdir(parents=True, exist_ok=True)
                    dest_path = torrents_dir / f"{uuid.uuid4()}.torrent"
                    try:
                        shutil.move(temp_path, dest_path)
                        target_url = f"torrent:{dest_path.absolute()}"
                    except Exception as e:
                        log.exception("Failed to save replied torrent file")
                        await message.reply_text(f"Failed to save torrent file: {e}")
                        return
                else:
                    await message.reply_text("Failed to download replied torrent file.")
                    return

        if not target_url:
            parts = message.text.split(maxsplit=1)
            if len(parts) < 2:
                await message.reply_text("Send a magnet link or reply to a `.torrent` file with `/tor <magnet/url>`.")
                return
            
            input_url = parts[1].strip()
            if input_url.startswith("magnet:") or input_url.startswith(("http://", "https://")):
                target_url = input_url
            else:
                await message.reply_text("Please provide a valid magnet link or torrent URL.")
                return

        url_display = target_url
        if target_url.startswith("magnet:"):
            url_display = target_url[:60] + "..." if len(target_url) > 60 else target_url
        elif target_url.startswith("torrent:"):
            url_display = "local torrent file"

        await _create_and_enqueue_job(message.chat.id, target_url, message, url_display)

    @app.on_message(filters.command("pdup"))
    async def pdup_cmd(_, message: Message) -> None:
        if not message.reply_to_message:
            await message.reply_text("Please reply to a media message to upload it to Pixeldrain.")
            return

        reply_msg = message.reply_to_message
        if not (reply_msg.document or reply_msg.video or reply_msg.photo or reply_msg.audio or reply_msg.voice):
            await message.reply_text("Replied message does not contain a supported media file.")
            return

        status_msg = await message.reply_text("Downloading media file for Pixeldrain upload...")
        temp_dir = settings.data_dir / "temp_pdup"
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        file_path_str = await reply_msg.download(file_name=str(temp_dir) + "/")
        if not file_path_str or not Path(file_path_str).exists():
            await status_msg.edit_text("Failed to download media file from Telegram.")
            return

        local_path = Path(file_path_str)
        try:
            await status_msg.edit_text(f"Uploading `{local_path.name}` to Pixeldrain...")
            domain = settings.pixeldrain_domain or "pixeldrain.com"
            res, _ = await upload_to_pixeldrain(
                local_path,
                api_key=settings.pixeldrain_api_key,
                domain=domain
            )

            if isinstance(res, dict) and res.get("id"):
                pd_url = f"https://{domain}/u/{res['id']}"
                await status_msg.edit_text(
                    f"**Pixeldrain Upload Complete**\n"
                    f"------------------------------------\n"
                    f"- **File**: `{local_path.name}`\n"
                    f"- **URL**: {pd_url}"
                )
            else:
                err = res.get("error") if isinstance(res, dict) else "Unknown error"
                await status_msg.edit_text(f"Failed to upload to Pixeldrain: {err}")
        except Exception as e:
            log.exception("Error uploading file to Pixeldrain")
            await status_msg.edit_text(f"Pixeldrain upload failed: {e}")
        finally:
            if local_path.exists():
                local_path.unlink(missing_ok=True)

    @app.on_message(filters.command(["gd2tg"]))
    async def gd2tg_cmd(_, message: Message) -> None:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            await message.reply_text("Provide a Google Drive link: `/gd2tg <gdrive_link>`.")
            return

        raw_link = parts[1].strip()
        link = f"gd2tg:{raw_link}"
        await _create_and_enqueue_job(message.chat.id, link, message, raw_link)

    @app.on_message(filters.text & ~filters.command(["start", "help", "status", "cancel", "gdl", "tor", "unzip", "gd2tg", "pdup", "direct", "dl", "m", "mirror"]))
    async def url_message_listener(_, message: Message) -> None:
        text = message.text.strip()
        if not (text.startswith(("http://", "https://", "magnet:", "direct:")) or "drive.google.com" in text or "docs.google.com" in text):
            return

        await _create_and_enqueue_job(message.chat.id, text, message, text)
