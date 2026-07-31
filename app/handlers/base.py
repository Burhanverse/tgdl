from __future__ import annotations

from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, LinkPreviewOptions

from ..auth import authorized_filter
from .help_content import get_help_content


def register_base_handlers(app: Client) -> None:

    @app.on_message(filters.command(["start", "help"]) & authorized_filter)
    async def start_cmd(_, message: Message) -> None:
        text, keyboard = get_help_content("main")
        await message.reply_text(
            text,
            reply_markup=keyboard,
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )

    @app.on_callback_query(filters.regex(r"^help_page:(main|dl|tor|unzip|cloud|config|close)$") & authorized_filter)
    async def help_page_cb(_, query: CallbackQuery) -> None:
        match = query.matches[0]
        page = match.group(1)

        if page == "close":
            await query.answer("Closed help menu.")
            try:
                await query.message.delete()
            except Exception:
                pass
            return

        await query.answer()
        text, keyboard = get_help_content(page)
        try:
            await query.message.edit_text(
                text,
                reply_markup=keyboard,
                link_preview_options=LinkPreviewOptions(is_disabled=True)
            )
        except Exception:
            pass

    @app.on_message(filters.service)
    async def auto_delete_service_messages(_, message: Message) -> None:
        if message.pinned_message or getattr(message, "service", False):
            try:
                await message.delete()
            except Exception:
                pass

