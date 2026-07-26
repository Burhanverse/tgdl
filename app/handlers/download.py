from __future__ import annotations

import asyncio
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
from ..manager.status.messaging import safe_send
from ..uploader import upload_to_pixeldrain, upload_to_gofile, upload_to_fileditch

log = logging.getLogger(__name__)


async def _create_and_enqueue_job(
    chat_id: int,
    target_url: str,
    message: Message,
    display_text: str,
    is_mirror: bool = False
) -> None:
    args_json = json.dumps({"is_mirror": True}) if is_mirror else None
    job = await store.create_job(chat_id, target_url, split_large_files=1, args=args_json)
    await store.update_progress(job.id, status="queued")
    await queue_manager.add_job(job.id)
    await asyncio.sleep(0.4)

    db_j = await store.get_job(job.id)
    if db_j and db_j.status == "queued" and job.id not in queue_manager.jobs:
        queued_text = compile_queued_status_text(job.id, display_text, "")
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Cancel", callback_data=f"cancel_job:{job.id}")]
        ])
        status_msg = await safe_send(
            message.client,
            chat_id,
            queued_text,
            reply_markup=keyboard,
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        if status_msg:
            await store.set_status_message(job.id, status_msg.id)

            async def auto_delete_queued():
                await asyncio.sleep(10)
                try:
                    cur_j = await store.get_job(job.id)
                    if cur_j and cur_j.status == "queued":
                        await message.client.delete_messages(chat_id, status_msg.id)
                except Exception:
                    pass

            asyncio.create_task(auto_delete_queued())


def register_download_handlers(app: Client) -> None:

    @app.on_message(filters.command(["m", "mirror"]))
    async def mirror_cmd(_, message: Message) -> None:
        target_url = None
        display_text = "Mirror"

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
                display_text = f"Mirror: Telegram file `{file_name}`"

        if not target_url:
            parts = message.text.split(maxsplit=1)
            if len(parts) >= 2:
                raw_link = parts[1].strip()
                target_url = f"mirror:{raw_link}"
                display_text = f"Mirror: {raw_link}"

        if not target_url:
            await message.reply_text("Provide a URL or reply to a Telegram media message with `/m` or `/mirror`.")
            return

        await _create_and_enqueue_job(message.chat.id, target_url, message, display_text, is_mirror=True)

    @app.on_message(filters.command(["direct", "dl"]))
    async def direct_cmd(_, message: Message) -> None:
        urls = []
        text_tokens = message.text.split()
        is_mirror = ("-m" in text_tokens) or ("-mirror" in text_tokens)

        if message.reply_to_message:
            reply_msg = message.reply_to_message

            if reply_msg.document and (
                reply_msg.document.file_name.endswith(".txt") or
                (reply_msg.document.mime_type and reply_msg.document.mime_type.startswith("text/"))
            ):
                temp_path = await reply_msg.download()
                if temp_path and Path(temp_path).exists():
                    try:
                        content = Path(temp_path).read_text(encoding="utf-8", errors="ignore")
                        for line in content.splitlines():
                            line = line.strip()
                            if line.startswith(("http://", "https://")):
                                urls.append(line)
                    except Exception as e:
                        log.warning("Failed reading replied txt file for direct_cmd: %s", e)
                    finally:
                        Path(temp_path).unlink(missing_ok=True)

            reply_text = reply_msg.text or reply_msg.caption
            if reply_text and not urls:
                for token in reply_text.split():
                    token = token.strip()
                    if token.startswith(("http://", "https://")):
                        urls.append(token)

        if not urls:
            for token in text_tokens[1:]:
                token = token.strip()
                if token in ("-m", "-mirror"):
                    continue
                if token.startswith(("http://", "https://")):
                    urls.append(token)

        if not urls:
            await message.reply_text(
                "Provide a direct URL or reply to a text/message containing URLs:\n"
                "• `/direct [-m|-mirror] <url>` or `/dl [-m] <url>`\n"
                "• Reply with `/direct [-m]` or `/dl [-m]` to a text message or `.txt` file containing URLs."
            )
            return

        urls_json = json.dumps([f"direct:{u}" for u in urls]) if len(urls) > 1 else f"direct:{urls[0]}"
        prefix = "direct [mirror]:" if is_mirror else "direct:"
        display_text = f"{prefix} `{urls[0]}`" if len(urls) == 1 else f"{prefix} `{urls[0]}` (+ {len(urls) - 1} more)"
        await _create_and_enqueue_job(message.chat.id, urls_json, message, display_text, is_mirror=is_mirror)

    @app.on_message(filters.command(["gallerydl", "gdl"]))
    async def gdl_cmd(_, message: Message) -> None:
        urls = []
        text_tokens = message.text.split()
        is_mirror = ("-m" in text_tokens) or ("-mirror" in text_tokens)

        if message.reply_to_message:
            reply_msg = message.reply_to_message

            if reply_msg.document and (
                reply_msg.document.file_name.endswith(".txt") or
                (reply_msg.document.mime_type and reply_msg.document.mime_type.startswith("text/"))
            ):
                temp_path = await reply_msg.download()
                if temp_path and Path(temp_path).exists():
                    try:
                        content = Path(temp_path).read_text(encoding="utf-8", errors="ignore")
                        for line in content.splitlines():
                            line = line.strip()
                            if line.startswith(("http://", "https://")):
                                urls.append(line)
                    except Exception as e:
                        log.warning("Failed reading replied txt file: %s", e)
                    finally:
                        Path(temp_path).unlink(missing_ok=True)

            reply_text = reply_msg.text or reply_msg.caption
            if reply_text and not urls:
                for token in reply_text.split():
                    token = token.strip()
                    if token.startswith(("http://", "https://")):
                        urls.append(token)

        if not urls:
            for token in text_tokens[1:]:
                token = token.strip()
                if token in ("-m", "-mirror"):
                    continue
                if token.startswith(("http://", "https://")):
                    urls.append(token)

        if not urls:
            await message.reply_text(
                "Provide a URL or reply to a text/message containing URLs:\n"
                "• `/gdl [-m|-mirror] <url>`\n"
                "• Reply with `/gdl [-m]` to a text message or `.txt` file containing URLs."
            )
            return

        urls_json = json.dumps(urls) if len(urls) > 1 else urls[0]
        prefix = "gallery-dl [mirror]:" if is_mirror else "gallery-dl:"
        display_text = f"{prefix} `{urls[0]}`" if len(urls) == 1 else f"{prefix} `{urls[0]}` (+ {len(urls) - 1} more)"
        await _create_and_enqueue_job(message.chat.id, urls_json, message, display_text, is_mirror=is_mirror)

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
                    f"**[Pixeldrain Upload Complete]({pd_url})**\n"
                    f"**File**: `{local_path.name}`",
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
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

    @app.on_message(filters.command(["gfup", "gofile"]))
    async def gfup_cmd(_, message: Message) -> None:
        if not message.reply_to_message:
            await message.reply_text("Please reply to a media message with `/gfup` or `/gofile` to upload it to GoFile.")
            return

        reply_msg = message.reply_to_message
        if not (reply_msg.document or reply_msg.video or reply_msg.photo or reply_msg.audio or reply_msg.voice):
            await message.reply_text("Replied message does not contain a supported media file.")
            return

        status_msg = await message.reply_text("Downloading media file for GoFile upload...")
        temp_dir = settings.data_dir / "temp_gfup"
        temp_dir.mkdir(parents=True, exist_ok=True)

        file_path_str = await reply_msg.download(file_name=str(temp_dir) + "/")
        if not file_path_str or not Path(file_path_str).exists():
            await status_msg.edit_text("Failed to download media file from Telegram.")
            return

        local_path = Path(file_path_str)
        try:
            await status_msg.edit_text(f"Uploading `{local_path.name}` to GoFile...")
            res, _ = await upload_to_gofile(local_path)

            if isinstance(res, dict) and res.get("status") == "ok":
                gf_url = res.get("data", {}).get("downloadPage")
                await status_msg.edit_text(
                    f"**[GoFile Upload Complete]({gf_url})**\n"
                    f"**File**: `{local_path.name}`",
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )
            else:
                err = res.get("error") if isinstance(res, dict) else "Unknown error"
                await status_msg.edit_text(f"Failed to upload to GoFile: {err}")
        except Exception as e:
            log.exception("Error uploading file to GoFile")
            await status_msg.edit_text(f"GoFile upload failed: {e}")
        finally:
            if local_path.exists():
                local_path.unlink(missing_ok=True)

    @app.on_message(filters.command(["fdup", "fileditch"]))
    async def fdup_cmd(_, message: Message) -> None:
        if not message.reply_to_message:
            await message.reply_text("Please reply to a media message with `/fdup` or `/fileditch` to upload it to FileDitch.")
            return

        reply_msg = message.reply_to_message
        if not (reply_msg.document or reply_msg.video or reply_msg.photo or reply_msg.audio or reply_msg.voice):
            await message.reply_text("Replied message does not contain a supported media file.")
            return

        status_msg = await message.reply_text("Downloading media file for FileDitch upload...")
        temp_dir = settings.data_dir / "temp_fdup"
        temp_dir.mkdir(parents=True, exist_ok=True)

        file_path_str = await reply_msg.download(file_name=str(temp_dir) + "/")
        if not file_path_str or not Path(file_path_str).exists():
            await status_msg.edit_text("Failed to download media file from Telegram.")
            return

        local_path = Path(file_path_str)
        try:
            await status_msg.edit_text(f"Uploading `{local_path.name}` to FileDitch...")
            res, _ = await upload_to_fileditch(local_path)

            if isinstance(res, dict) and res.get("success") is True:
                fd_url = res.get("url")
                await status_msg.edit_text(
                    f"**[FileDitch Upload Complete]({fd_url})**\n"
                    f"**File**: `{local_path.name}`",
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )
            else:
                err = res.get("error") if isinstance(res, dict) else "Unknown error"
                await status_msg.edit_text(f"Failed to upload to FileDitch: {err}")
        except Exception as e:
            log.exception("Error uploading file to FileDitch")
            await status_msg.edit_text(f"FileDitch upload failed: {e}")
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
