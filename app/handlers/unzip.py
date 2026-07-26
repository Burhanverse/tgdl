from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, LinkPreviewOptions

from ..config import settings
from ..middleware import is_job_owner
from ..manager.core import queue_manager, store, _password_prompt_events, _password_prompt_messages
from ..manager.status.compiler import (
    compile_split_prompt_text,
    compile_queued_status_text,
    compile_unzip_download_status_text,
)
from ..manager.archive import ARCHIVE_EXT, extract_archive_async, ArchivePasswordRequired
from ..manager.multi_unzip import (
    start_multi_unzip_session,
    handle_multi_document,
    handle_multi_cancel_cb,
    handle_multi_start_cb,
)

log = logging.getLogger(__name__)

_split_archive_sessions: dict[int, dict] = {}


def compile_split_session_text(prefix: str, ext: str, parts: dict[int, Message]) -> str:
    sorted_parts = sorted(parts.keys())
    parts_list = []
    max_part = max(sorted_parts) if sorted_parts else 0
    
    for i in range(1, max_part + 2):
        if i in parts:
            filename = parts[i].document.file_name
            parts_list.append(f"**Part {i}**: `{filename}`")
        else:
            if i == 1 or i <= max_part:
                parts_list.append(f"**Part {i}**: _Waiting for file..._")
            else:
                break
                
    parts_str = "\n".join(parts_list)
    
    text = (
        f"**Split Archive Session**\n"
        f"- **Base Pattern**: `{prefix}.*`\n\n"
        f"**Instructions:**\n"
        f"Please upload/forward the remaining parts of this archive to this chat.\n\n"
        f"**Parts Received:**\n"
        f"{parts_str}\n\n"
        f"When all parts are uploaded, click **Start Extraction** below."
    )
    return text


def register_unzip_handlers(app: Client) -> None:

    @app.on_message(filters.command("unzip"))
    async def unzip_cmd(_, message: Message) -> None:
        tokens = (message.text or "").split()[1:]
        lowered_tokens = [t.lower() for t in tokens]

        if "multi" in lowered_tokens:
            password = next((t for t in tokens if t.lower() != "multi"), None)
            await start_multi_unzip_session(message, password=password, split_archive_sessions=_split_archive_sessions)
            return

        if "split" in lowered_tokens:
            password = next((t for t in tokens if t.lower() != "split"), None)
            chat_id = message.chat.id
            user_id = message.from_user.id if message.from_user else chat_id
            session_key = chat_id
            
            if session_key in _split_archive_sessions:
                old_session = _split_archive_sessions.pop(session_key)
                if old_session.get("timeout_task"):
                    old_session["timeout_task"].cancel()
                try:
                    await old_session["status_msg"].edit_text("**Session replaced by a new one.**")
                except Exception:
                    pass
                    
            def get_split_session_keyboard(c_id: int, u_id: int) -> InlineKeyboardMarkup:
                return InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("Start Extraction", callback_data=f"split_start:{c_id}:{u_id}"),
                        InlineKeyboardButton("Cancel", callback_data=f"split_cancel:{c_id}:{u_id}")
                    ]
                ])
                
            status_msg = await message.reply_text(
                "**Split Archive Session Started**\n\n"
                "Please send or forward the split archive parts (e.g. `.001`, `.002`, or `.part1.rar` files) to this chat.\n\n"
                "**Waiting for files...**",
                reply_markup=get_split_session_keyboard(chat_id, user_id)
            )
            
            async def split_session_timeout(c_id: int, delay: int = 300):
                await asyncio.sleep(delay)
                s_key = c_id
                if s_key in _split_archive_sessions:
                    session = _split_archive_sessions.pop(s_key)
                    try:
                        await session["status_msg"].edit_text("**Split Archive Session Expired** (Timeout due to inactivity).")
                    except Exception:
                        pass

            timeout_task = asyncio.create_task(split_session_timeout(chat_id))
            _split_archive_sessions[session_key] = {
                "user_id": user_id,
                "password": password,
                "parts": {},
                "prefix": None,
                "ext": None,
                "status_msg": status_msg,
                "timeout_task": timeout_task,
            }
            return

        if not message.reply_to_message or not message.reply_to_message.document:
            await message.reply_text("Reply to an archive with `/unzip [password]` or use `/unzip split [password]` or `/unzip multi [password]`.")
            return

        doc = message.reply_to_message.document
        ext = Path(doc.file_name).suffix.lower()
        if ext not in ARCHIVE_EXT:
            await message.reply_text(f"File `{doc.file_name}` is not a supported archive format.")
            return

        password = tokens[0] if tokens else None
        target_url = f"unzip:{doc.file_name}"
        import json
        args_json = json.dumps({"reply_message_id": message.reply_to_message.id, "password": password})
        job = await store.create_job(message.chat.id, target_url, split_large_files=1, args=args_json)
        await store.update_progress(job.id, status="waiting")

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Yes, split them", callback_data=f"split_yes:{job.id}"),
                InlineKeyboardButton("No, skip them", callback_data=f"split_no:{job.id}")
            ],
            [
                InlineKeyboardButton("Cancel", callback_data=f"cancel_job:{job.id}")
            ]
        ])

        prompt_text = compile_split_prompt_text(job.id, doc.file_name, is_unzip=True)
        status_msg = await message.reply_text(
            prompt_text,
            reply_markup=keyboard,
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        await store.set_status_message(job.id, status_msg.id)

    @app.on_message(filters.text, group=-1)
    async def password_reply_listener(_, message: Message) -> None:
        if not message.reply_to_message or message.reply_to_message.id not in _password_prompt_events:
            return

        prompt_msg_id = message.reply_to_message.id
        event = _password_prompt_events.get(prompt_msg_id)
        if event:
            _password_prompt_messages[prompt_msg_id] = message.text.strip()
            event.set()

    @app.on_message(group=-2)
    async def document_intercept_listener(_, message: Message) -> None:
        if not message.document:
            return

        chat_id = message.chat.id
        handled_multi = await handle_multi_document(message, _split_archive_sessions)
        if handled_multi:
            return

        if chat_id not in _split_archive_sessions:
            return

        session = _split_archive_sessions[chat_id]
        if message.from_user and message.from_user.id != session["user_id"]:
            return

        doc = message.document
        filename = doc.file_name

        from ..manager.archive import get_split_archive_info
        prefix, ext, part_num = get_split_archive_info(filename)
        if part_num is None:
            return

        if session["prefix"] is None:
            session["prefix"] = prefix
            session["ext"] = ext
        elif session["prefix"] != prefix:
            await message.reply_text(f"File `{filename}` doesn't match the current split archive pattern (`{session['prefix']}.*`).")
            return

        session["parts"][part_num] = message
        if session.get("timeout_task"):
            session["timeout_task"].cancel()
            
        async def reset_timeout():
            await asyncio.sleep(300)
            if chat_id in _split_archive_sessions:
                s = _split_archive_sessions.pop(chat_id)
                try:
                    await s["status_msg"].edit_text("**Split Archive Session Expired** (Timeout due to inactivity).")
                except Exception:
                    pass
                    
        session["timeout_task"] = asyncio.create_task(reset_timeout())
        updated_text = compile_split_session_text(session["prefix"], session["ext"], session["parts"])
        try:
            await session["status_msg"].edit_text(
                updated_text,
                reply_markup=session["status_msg"].reply_markup
            )
        except Exception:
            pass

    @app.on_callback_query(filters.regex(r"^split_cancel:(-?\d+):(-?\d+)$"))
    async def split_cancel_cb(_, query: CallbackQuery) -> None:
        match = query.matches[0]
        chat_id = int(match.group(1))
        user_id = int(match.group(2))

        if query.from_user.id != user_id and query.message.chat.id != chat_id:
            await query.answer("You are not authorized to cancel this session.", show_alert=True)
            return

        session = _split_archive_sessions.pop(chat_id, None)
        if session and session.get("timeout_task"):
            session["timeout_task"].cancel()

        await query.answer("Split archive session cancelled.")
        await query.message.edit_text("**Split Archive Session Cancelled.**")

    @app.on_callback_query(filters.regex(r"^split_start:(-?\d+):(-?\d+)$"))
    async def split_start_cb(_, query: CallbackQuery) -> None:
        match = query.matches[0]
        chat_id = int(match.group(1))
        user_id = int(match.group(2))

        if query.from_user.id != user_id and query.message.chat.id != chat_id:
            await query.answer("You are not authorized to start this session.", show_alert=True)
            return

        session = _split_archive_sessions.get(chat_id)
        if not session or not session["parts"]:
            await query.answer("No split archive parts received yet!", show_alert=True)
            return

        await query.answer("Starting extraction...")

    @app.on_callback_query(filters.regex(r"^multi_cancel:(-?\d+):(-?\d+)$"))
    async def multi_cancel_cb(_, query: CallbackQuery) -> None:
        await handle_multi_cancel_cb(query, _split_archive_sessions)

    @app.on_callback_query(filters.regex(r"^multi_start:(-?\d+):(-?\d+)$"))
    async def multi_start_cb(_, query: CallbackQuery) -> None:
        await handle_multi_start_cb(query, _split_archive_sessions)
