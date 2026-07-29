from __future__ import annotations

import html
import logging
from pyrogram import Client, filters
from pyrogram.handlers import CallbackQueryHandler, MessageHandler
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..config import settings
from ..downloader.torrent import (
    SITES,
    format_search_results_html,
    initiate_search_tools,
    search_torrents,
    telegraph_helper,
)

log = logging.getLogger(__name__)


def build_search_keyboard(user_id: int, mode: str = "main") -> InlineKeyboardMarkup:
    """Builds inline keyboards for torrent search modes."""
    buttons = []

    if mode == "main":
        if SITES and len(SITES) > 1:
            return build_search_keyboard(user_id, "api_sites")

        buttons.append([
            InlineKeyboardButton("Trending", callback_data=f"torser:{user_id}:apitrend"),
            InlineKeyboardButton("Recent", callback_data=f"torser:{user_id}:apirecent"),
        ])
        buttons.append([InlineKeyboardButton("Cancel", callback_data=f"torser:{user_id}:cancel")])

    elif mode == "api_sites":
        site_btns = []
        if SITES:
            for site_key, site_name in SITES.items():
                site_btns.append(InlineKeyboardButton(site_name, callback_data=f"torser:{user_id}:apisearch:{site_key}"))
        for i in range(0, len(site_btns), 2):
            buttons.append(site_btns[i:i + 2])
        buttons.append([InlineKeyboardButton("Cancel", callback_data=f"torser:{user_id}:cancel")])

    return InlineKeyboardMarkup(buttons)


async def handle_torrent_search(client: Client, message: Message) -> None:
    """Command handler for /torsearch and /ts."""
    user_id = message.from_user.id if message.from_user else message.chat.id
    cmd_text = message.text or ""
    parts = cmd_text.split(maxsplit=1)

    if len(parts) == 1:
        kb = build_search_keyboard(user_id, "main")
        await message.reply_text(
            "<b>Torrent Search</b>\nSend a search term with command: <code>/torsearch [query]</code> or <code>/ts [query]</code>",
            reply_markup=kb if SITES and len(SITES) > 1 else None
        )
        return

    query = parts[1].strip()
    safe_query = html.escape(query)
    if SITES and len(SITES) > 1:
        kb = build_search_keyboard(user_id, "main")
        await message.reply_text(f"<b>Searching for:</b> <code>{safe_query}</code>\nChoose search backend/site:", reply_markup=kb)
    else:
        status_msg = await message.reply_text(f"<b>Searching torrents for:</b> <code>{safe_query}</code>...")
        try:
            results = await search_torrents(query, site="public", method="fallback")
            telegraph_url = await telegraph_helper.generate_telegraph_page(results, query, "Public Indexers")
            if telegraph_url:
                reply_kb = InlineKeyboardMarkup([[InlineKeyboardButton("VIEW", url=telegraph_url)]])
                msg = f"<b>Found {len(results)} result(s) for <i>{html.escape(query)}</i>\nTorrent Site: <i>Public Indexers</i></b>"
                await status_msg.edit_text(msg, reply_markup=reply_kb)
            else:
                formatted_html = format_search_results_html(results, query, "Public Indexers")
                await status_msg.edit_text(formatted_html, disable_web_page_preview=True)
        except Exception as e:
            log.exception("Torrent search failed: %s", e)
            await status_msg.edit_text(f"<b>Search error:</b> {e}")


async def handle_torrent_search_callback(client: Client, callback: CallbackQuery) -> None:
    """Callback query handler for torrent search buttons."""
    data = callback.data or ""
    if not data.startswith("torser:"):
        return

    parts = data.split(":")
    if len(parts) < 3:
        await callback.answer("Invalid callback data", show_alert=True)
        return

    target_user_id = int(parts[1])
    action = parts[2]

    user_id = callback.from_user.id if callback.from_user else callback.message.chat.id
    if user_id != target_user_id:
        await callback.answer("This search menu is not yours!", show_alert=True)
        return

    if action == "cancel":
        await callback.answer("Cancelled search.")
        await callback.message.edit_text("Search cancelled.")
        return

    if action == "apisearch" and len(parts) == 3:
        await callback.answer()
        kb = build_search_keyboard(target_user_id, "api_sites")
        await callback.message.edit_text("<b>Select Search API Site:</b>", reply_markup=kb)
        return

    if action == "plugin" and len(parts) == 3:
        await callback.answer()
        kb = build_search_keyboard(target_user_id, "plugin_sites")
        await callback.message.edit_text("<b>Select Plugin Site:</b>", reply_markup=kb)
        return

    # Extract search query from original message or reply message
    query_text = ""
    orig_text = callback.message.text or ""
    if "Searching for:" in orig_text:
        query_text = orig_text.split("Searching for:")[1].split("\n")[0].strip().strip("<code>").strip("</code>")
    elif callback.message.reply_to_message and callback.message.reply_to_message.text:
        q_parts = callback.message.reply_to_message.text.split(maxsplit=1)
        if len(q_parts) > 1:
            query_text = q_parts[1].strip()

    site = parts[3] if len(parts) > 3 else "all"
    method = action

    await callback.answer("Searching torrents...")
    await callback.message.edit_text(f"<b>Searching torrents for:</b> <code>{query_text or 'trending'}</code>...")

    try:
        results = await search_torrents(query_text, site=site, method=method)
        telegraph_url = await telegraph_helper.generate_telegraph_page(results, query_text or "trending", site)
        if telegraph_url:
            reply_kb = InlineKeyboardMarkup([[InlineKeyboardButton("VIEW", url=telegraph_url)]])
            msg = f"<b>Found {len(results)} result(s) for <i>{html.escape(query_text or 'trending')}</i>\nTorrent Site: <i>{html.escape(site.capitalize())}</i></b>"
            await callback.message.edit_text(msg, reply_markup=reply_kb)
        else:
            formatted_html = format_search_results_html(results, query_text or "trending", site)
            await callback.message.edit_text(formatted_html, disable_web_page_preview=True)
    except Exception as e:
        log.exception("Torrent search failed: %s", e)
        await callback.message.edit_text(f"<b>Search error:</b> {e}")


def register_torrent_search_handlers(app: Client) -> None:
    """Registers torrent search handlers on Pyrogram Client."""
    app.add_handler(MessageHandler(handle_torrent_search, filters.command(["torsearch", "ts", "search"])))
    app.add_handler(CallbackQueryHandler(handle_torrent_search_callback, filters.regex(r"^torser:")))
