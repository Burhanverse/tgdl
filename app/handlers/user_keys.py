from __future__ import annotations

import logging

from pyrogram import Client, filters
from pyrogram.types import Message

from ..auth import authorized_filter
from ..uploader.user_keys import (
    delete_user_upload_key,
    get_user_upload_keys,
    save_user_upload_key,
)

log = logging.getLogger(__name__)


def register_user_key_handlers(app: Client) -> None:

    @app.on_message(filters.command(["gofilekey", "gofile_key"]) & authorized_filter)
    async def gofile_key_cmd(_, message: Message) -> None:
        user_id = message.from_user.id if message.from_user else None
        if not user_id:
            await message.reply_text("Error: Cannot identify user ID.")
            return

        text = message.text or ""
        parts = text.split(maxsplit=1)
        arg = parts[1].strip() if len(parts) > 1 else ""

        if not arg:
            keys = get_user_upload_keys(user_id)
            current = keys.get("gofile")
            if current:
                masked = current[:4] + "*" * (len(current) - 4) if len(current) > 4 else "****"
                await message.reply_text(
                    f"**GoFile API Key**: `Set ({masked})`\n\n"
                    f"To update: `/gofilekey <your_api_token>`\n"
                    f"To delete: `/gofilekey delete`"
                )
            else:
                await message.reply_text(
                    "**GoFile API Key**: `Not Set`\n\n"
                    "Provide your token: `/gofilekey <your_api_token>`"
                )
            return

        if arg.lower() in ("del", "delete", "remove", "clear"):
            delete_user_upload_key(user_id, "gofile")
            await message.reply_text("Deleted your personal GoFile API key.")
            return

        save_user_upload_key(user_id, "gofile", arg)
        masked = arg[:4] + "*" * (len(arg) - 4) if len(arg) > 4 else "****"
        await message.reply_text(f"Saved personal GoFile API key (`{masked}`).")

    @app.on_message(filters.command(["pdkey", "pixeldrainkey", "pd_key"]) & authorized_filter)
    async def pd_key_cmd(_, message: Message) -> None:
        user_id = message.from_user.id if message.from_user else None
        if not user_id:
            await message.reply_text("Error: Cannot identify user ID.")
            return

        text = message.text or ""
        parts = text.split(maxsplit=1)
        arg = parts[1].strip() if len(parts) > 1 else ""

        if not arg:
            keys = get_user_upload_keys(user_id)
            current = keys.get("pixeldrain")
            if current:
                masked = current[:4] + "*" * (len(current) - 4) if len(current) > 4 else "****"
                await message.reply_text(
                    f"**Pixeldrain API Key**: `Set ({masked})`\n\n"
                    f"To update: `/pdkey <your_api_key>`\n"
                    f"To delete: `/pdkey delete`"
                )
            else:
                await message.reply_text(
                    "**Pixeldrain API Key**: `Not Set`\n\n"
                    "Provide your key: `/pdkey <your_api_key>`"
                )
            return

        if arg.lower() in ("del", "delete", "remove", "clear"):
            delete_user_upload_key(user_id, "pixeldrain")
            await message.reply_text("Deleted your personal Pixeldrain API key.")
            return

        save_user_upload_key(user_id, "pixeldrain", arg)
        masked = arg[:4] + "*" * (len(arg) - 4) if len(arg) > 4 else "****"
        await message.reply_text(f"Saved personal Pixeldrain API key (`{masked}`).")
