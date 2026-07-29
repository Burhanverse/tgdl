from __future__ import annotations

from pyrogram import Client, filters
from pyrogram.types import Message, LinkPreviewOptions


def register_base_handlers(app: Client) -> None:

    @app.on_message(filters.command(["start", "help"]))
    async def start_cmd(_, message: Message) -> None:
        text = (
            "Send me links to download media files (e.g., videos, photo albums) and upload them to Telegram.\n\n"
            "**Usage:**\n"
            "• Simply paste any supported URL or magnet link into the chat.\n"
            "• Forward or upload a `.torrent` file or reply to a `.torrent` file with `/tor`.\n"
            "• Reply to any archive with `/unzip [password]` or use `/unzip split [password]` or `/unzip multi [password]`.\n"
            "• Reply to any media file with `/pdup` to upload it directly to Pixeldrain.\n\n"
            "**Commands:**\n"
            "• `/status` — View active download/upload metrics, task list, pagination, and overall speeds.\n"
            "• `/cancel [job_id]` — Cancel an active or queued job.\n"
            "• `/gdl [args]` — Submit text file containing URLs.\n"
            "• `/gdlconf` — View and manage your `gallery-dl.conf` configuration.\n"
            "• `/tor [magnet/url]` — Download torrent file or magnet link.\n"
            "• `/unzip [password]` — Extract archive file.\n"
            "• `/pdup` — Upload replied file to Pixeldrain.\n"
            "• `/gd2tg [link]` — Download Google Drive link to Telegram.\n"
        )
        await message.reply_text(text, link_preview_options=LinkPreviewOptions(is_disabled=True))

    @app.on_message(filters.service)
    async def auto_delete_service_messages(_, message: Message) -> None:
        if message.pinned_message or getattr(message, "service", False):
            try:
                await message.delete()
            except Exception:
                pass
