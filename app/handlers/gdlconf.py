from __future__ import annotations

import json
import logging
import re
import shutil
import time
from pathlib import Path
from typing import Optional

from pyrogram import Client, filters
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
)

from ..config import settings
from ..downloader import get_gdl_config_path, get_user_gdl_config_path

log = logging.getLogger(__name__)


def _strip_comments(json_str: str) -> str:
    """Strips '#' key comment lines and standard single/multi-line comments for JSON validation."""
    lines = []
    for line in json_str.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        lines.append(line)
    text = "\n".join(lines)
    # Remove trailing commas inside objects/arrays before closing braces/brackets for lenient parsing
    text = re.sub(r",\s*([\]}])", r"\1", text)
    return text


def validate_gdl_conf(content: str) -> tuple[bool, str, Optional[dict]]:
    """Validates if content is a valid gallery-dl configuration structure."""
    if not content.strip():
        return False, "Configuration file is empty.", None

    clean_text = _strip_comments(content)
    try:
        data = json.loads(clean_text)
    except json.JSONDecodeError as e:
        return False, f"JSON Parsing Error: {e}", None

    if not isinstance(data, dict):
        return False, "Root element of gallery-dl configuration must be a JSON object (`{...}`).", None

    return True, "Valid gallery-dl configuration.", data


def _get_config_info(user_id: int) -> tuple[Path, bool, str, dict]:
    """Returns (active_path, is_user_specific, file_size_str, parsed_dict)."""
    user_conf = get_user_gdl_config_path(user_id)
    is_user_specific = user_conf.exists() and user_conf.is_file()
    active_path = get_gdl_config_path(user_id) or settings.gdl_config_path

    parsed_dict = {}
    size_str = "0 B"

    if active_path and active_path.exists():
        try:
            size_bytes = active_path.stat().st_size
            if size_bytes < 1024:
                size_str = f"{size_bytes} B"
            else:
                size_str = f"{size_bytes / 1024:.1f} KB"

            content = active_path.read_text(encoding="utf-8", errors="ignore")
            _, _, parsed_dict = validate_gdl_conf(content)
            parsed_dict = parsed_dict or {}
        except Exception as e:
            log.warning("Failed reading config info from %s: %s", active_path, e)

    return active_path, is_user_specific, size_str, parsed_dict


def build_gdlconf_text(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    active_path, is_user_specific, size_str, data = _get_config_info(user_id)

    scope_str = "**User-Specific** (`auth/{user_id}/gallery-dl.conf`)" if is_user_specific else "**Global Default** (`gallery-dl.conf`)"
    mtime_str = "N/A"
    if active_path and active_path.exists():
        mtime_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(active_path.stat().st_mtime))

    extractors = []
    if isinstance(data, dict) and "extractor" in data and isinstance(data["extractor"], dict):
        ext_dict = data["extractor"]
        for k, v in ext_dict.items():
            if isinstance(v, dict) and not k.startswith("#"):
                extractors.append(k)

    ext_summary = ", ".join(f"`{e}`" for e in extractors[:10]) if extractors else "None specified"
    if len(extractors) > 10:
        ext_summary += f" (+ {len(extractors) - 10} more)"

    text = (
        "**gallery-dl Configuration Status**\n\n"
        f"• **Scope**: {scope_str}\n"
        f"• **Config Path**: `{active_path}`\n"
        f"• **File Size**: `{size_str}`\n"
        f"• **Last Modified**: `{mtime_str}`\n"
        f"• **Configured Sites**: {ext_summary}\n\n"
        "**Usage Commands:**\n"
        "• Reply to a `.conf` or `.json` file with `/gdlconf` to upload your custom user configuration.\n"
        "• `/gdlconf get` — Download current configuration file.\n"
        "• `/gdlconf delete` — Delete your custom config & revert to global default.\n"
        "• `/gdlconf reset` — Reset your user config to default template."
    )

    buttons = [
        [
            InlineKeyboardButton("Download Conf", callback_data="gdlconf:get"),
            InlineKeyboardButton("Refresh", callback_data="gdlconf:view"),
        ]
    ]

    if is_user_specific:
        buttons.append([InlineKeyboardButton("🗑️ Delete Custom Conf", callback_data="gdlconf:delete")])
    else:
        buttons.append([InlineKeyboardButton("✨ Create User Template", callback_data="gdlconf:reset")])

    keyboard = InlineKeyboardMarkup(buttons)
    return text, keyboard


def _get_default_template_path() -> Optional[Path]:
    candidates = [
        Path(__file__).parent.parent / "downloader" / "gallery_dl" / "gallery-dl.conf",
        settings.gdl_config_path,
        Path("./gallery-dl.conf"),
    ]
    for c in candidates:
        if c and c.exists() and c.is_file():
            return c
    return None


def register_gdlconf_handlers(app: Client) -> None:

    @app.on_message(filters.command(["gdlconf", "gdl_config"]))
    async def gdlconf_cmd(_, message: Message) -> None:
        user_id = message.from_user.id if message.from_user else message.chat.id
        args = message.text.split(maxsplit=1)
        subcommand = args[1].strip().lower() if len(args) > 1 else ""

        # Case 1: User replied to a document file to set configuration
        if message.reply_to_message and message.reply_to_message.document:
            doc = message.reply_to_message.document
            if doc.file_name and (doc.file_name.endswith((".conf", ".json", ".txt")) or "json" in (doc.mime_type or "")):
                status_msg = await message.reply_text("Downloading & validating uploaded configuration file...")
                temp_path = await message.reply_to_message.download()
                if not temp_path or not Path(temp_path).exists():
                    await status_msg.edit_text("Failed to download configuration file.")
                    return

                try:
                    content = Path(temp_path).read_text(encoding="utf-8", errors="ignore")
                    ok, err_msg, parsed = validate_gdl_conf(content)
                    if not ok:
                        await status_msg.edit_text(f"**Invalid Configuration File**:\n`{err_msg}`")
                        return

                    user_conf_path = get_user_gdl_config_path(user_id)
                    user_conf_path.parent.mkdir(parents=True, exist_ok=True)
                    user_conf_path.write_text(content, encoding="utf-8")

                    await status_msg.edit_text(
                        f"**Saved user gallery-dl configuration!**\n"
                        f"Saved to: `auth/{user_id}/gallery-dl.conf`\n\n"
                        f"All subsequent `/gdl` downloads for your user account will use your custom settings."
                    )
                except Exception as e:
                    log.exception("Failed to save gallery-dl config for user %s", user_id)
                    await status_msg.edit_text(f"Failed to save configuration: `{e}`")
                finally:
                    Path(temp_path).unlink(missing_ok=True)
                return
            else:
                await message.reply_text("Please reply to a valid `.conf` or `.json` document file.")
                return

        # Case 2: Subcommands
        if subcommand in ("get", "download"):
            active_path = get_gdl_config_path(user_id) or _get_default_template_path()
            if active_path and active_path.exists():
                await message.reply_document(
                    document=str(active_path),
                    caption=f"**gallery-dl Configuration File** (`{active_path.name}`)"
                )
            else:
                await message.reply_text("Configuration file not found.")
            return

        elif subcommand in ("delete", "remove"):
            user_conf = get_user_gdl_config_path(user_id)
            if user_conf.exists():
                user_conf.unlink(missing_ok=True)
                await message.reply_text("Custom user `gallery-dl.conf` deleted! Reverted to default configuration.")
            else:
                await message.reply_text("ℹYou do not have a custom `gallery-dl.conf` saved. Currently using default configuration.")
            return

        elif subcommand in ("reset", "init"):
            default_template = _get_default_template_path()

            if default_template and default_template.exists():
                user_conf = get_user_gdl_config_path(user_id)
                user_conf.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(default_template, user_conf)
                await message.reply_text(f"Reset user config to default template: `auth/{user_id}/gallery-dl.conf`")
            else:
                await message.reply_text("Default template `gallery-dl.conf` not found.")
            return

        # Default view
        text, keyboard = build_gdlconf_text(user_id)
        await message.reply_text(text, reply_markup=keyboard, link_preview_options=LinkPreviewOptions(is_disabled=True))

    @app.on_callback_query(filters.regex(r"^gdlconf:"))
    async def gdlconf_callback(_, query: CallbackQuery) -> None:
        user_id = query.from_user.id if query.from_user else query.message.chat.id
        action = query.data.split(":")[1]

        if action == "view":
            text, keyboard = build_gdlconf_text(user_id)
            try:
                await query.message.edit_text(text, reply_markup=keyboard, link_preview_options=LinkPreviewOptions(is_disabled=True))
            except Exception:
                pass
            await query.answer("Refreshed status")

        elif action == "get":
            active_path = get_gdl_config_path(user_id) or _get_default_template_path()
            if active_path and active_path.exists():
                await query.message.reply_document(
                    document=str(active_path),
                    caption=f"**gallery-dl Configuration File** (`{active_path.name}`)"
                )
                await query.answer("Sending document...")
            else:
                await query.answer("Configuration file not found", show_alert=True)

        elif action == "delete":
            user_conf = get_user_gdl_config_path(user_id)
            if user_conf.exists():
                user_conf.unlink(missing_ok=True)
                await query.answer("Custom configuration deleted!", show_alert=True)
            else:
                await query.answer("No custom configuration found", show_alert=True)

            text, keyboard = build_gdlconf_text(user_id)
            try:
                await query.message.edit_text(text, reply_markup=keyboard, link_preview_options=LinkPreviewOptions(is_disabled=True))
            except Exception:
                pass

        elif action == "reset":
            default_template = _get_default_template_path()

            if default_template and default_template.exists():
                user_conf = get_user_gdl_config_path(user_id)
                user_conf.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(default_template, user_conf)
                await query.answer("User config reset to default template!", show_alert=True)
            else:
                await query.answer("Default template not found", show_alert=True)

            text, keyboard = build_gdlconf_text(user_id)
            try:
                await query.message.edit_text(text, reply_markup=keyboard, link_preview_options=LinkPreviewOptions(is_disabled=True))
            except Exception:
                pass
