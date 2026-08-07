from __future__ import annotations

import logging

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, Message

from ..auth import authorized_filter, is_owner
from ..manager.core import queue_manager
from ..manager.status import (
    MirrorStatus,
    get_all_active_task_adapters,
    get_readable_file_size,
    get_task_by_gid,
)
from ..utils.telegram import (
    ButtonMaker,
    delete_message,
    edit_message,
    send_status_message,
    update_status_message,
)
from ..utils.telegram.message_utils import (
    intervals,
    status_dict,
    task_dict_lock,
)

log = logging.getLogger(__name__)


def register_status_handlers(app: Client) -> None:

    @app.on_message(filters.command("status") & authorized_filter)
    async def status_cmd(_, message: Message) -> None:
        sender_id = message.from_user.id if message.from_user else message.chat.id
        text = message.text.split()
        user_is_owner = is_owner(sender_id)

        if user_is_owner:
            if len(text) > 1:
                arg = text[1].lower()
                if arg == "me":
                    user_id = sender_id
                elif arg == "all":
                    user_id = 0
                else:
                    try:
                        user_id = int(text[1])
                    except ValueError:
                        user_id = 0
            else:
                user_id = 0
        else:
            user_id = sender_id

        sid = user_id or message.chat.id
        async with task_dict_lock:
            if obj := intervals["status"].get(sid):
                if not obj.done():
                    obj.cancel()
                del intervals["status"][sid]

        await send_status_message(message, user_id)
        await delete_message(message)

    @app.on_callback_query(filters.regex(r"^status"))
    async def status_pages_cb(_, query: CallbackQuery) -> None:
        data = query.data.split()
        if len(data) < 3:
            await query.answer()
            return

        try:
            key = int(data[1])
        except (ValueError, TypeError, IndexError):
            await query.answer("Invalid callback key!", show_alert=True)
            return

        user_id = query.from_user.id if query.from_user else query.message.chat.id
        if not is_owner(user_id):
            if key == 0 or (key != query.message.chat.id and key != user_id):
                await query.answer("Not Yours!", show_alert=True)
                return

        action = data[2]

        if action == "cancel":
            gid = data[3] if len(data) > 3 else ""
            if not gid:
                await query.answer("Invalid request!", show_alert=True)
                return
            task = await get_task_by_gid(gid)
            if task is None:
                await query.answer("Task not found or already finished!", show_alert=True)
                return
            if not is_owner(user_id) and task.user_id and task.user_id != user_id and task.user_id != query.message.chat.id:
                await query.answer("Not Yours!", show_alert=True)
                return
            await query.answer(f"Cancelling job #{gid}...")
            await queue_manager.cancel_job(gid)
            await update_status_message(key, force=True)
            return

        await query.answer()
        if action == "ref":
            await update_status_message(key, force=True)
        elif action in ["nex", "pre"]:
            async with task_dict_lock:
                if key in status_dict:
                    if action == "nex":
                        status_dict[key]["page_no"] += status_dict[key]["page_step"]
                    else:
                        status_dict[key]["page_no"] -= status_dict[key]["page_step"]
            await update_status_message(key, force=True)
        elif action == "ps":
            async with task_dict_lock:
                if key in status_dict and len(data) > 3:
                    try:
                        status_dict[key]["page_step"] = int(data[3])
                    except (ValueError, TypeError):
                        # expected: invalid page_step payload
                        pass
            await update_status_message(key, force=True)
        elif action == "st":
            async with task_dict_lock:
                if key in status_dict and len(data) > 3:
                    status_dict[key]["status"] = data[3]
            await update_status_message(key, force=True)
        elif action == "ov":
            tasks_summary = await get_all_active_task_adapters()
            counts = {
                "Download": 0, "Upload": 0, "Archive": 0, "Extract": 0,
                "Split": 0, "Convert": 0, "QueueDl": 0, "Pause": 0,
            }
            total_dl_speed = 0.0
            total_ul_speed = 0.0
            for tk in tasks_summary:
                st = tk.status()
                if st in counts:
                    counts[st] += 1
                else:
                    counts["Download"] += 1

                if st == MirrorStatus.STATUS_UPLOAD:
                    total_ul_speed += tk.raw_speed()
                else:
                    total_dl_speed += tk.raw_speed()

            msg = (
                f"<b>DL:</b> {counts['Download']} | <b>UP:</b> {counts['Upload']} | "
                f"<b>AR:</b> {counts['Archive']} | <b>EX:</b> {counts['Extract']}\n"
                f"<b>SP:</b> {counts['Split']} | <b>CM:</b> {counts['Convert']} | "
                f"<b>QD:</b> {counts['QueueDl']} | <b>PA:</b> {counts['Pause']}\n\n"
                f"<b>Overall DL Speed:</b> {get_readable_file_size(total_dl_speed)}/s\n"
                f"<b>Overall UL Speed:</b> {get_readable_file_size(total_ul_speed)}/s\n"
            )
            buttons = ButtonMaker()
            buttons.data_button("Back", f"status {key} ref")
            await edit_message(query.message, msg, buttons.build_menu())
