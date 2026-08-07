from __future__ import annotations

import logging

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, Message

from .config import settings

log = logging.getLogger(__name__)


def is_authorized_user(update: Message | CallbackQuery) -> bool:
    """Checks whether the requesting user's Telegram user_id is in AUTHORIZED_USER_IDS.
    
    If AUTHORIZED_USER_IDS is empty/unset, returns True (unrestricted mode).
    """
    auth_users = settings.authorized_user_ids

    # Unrestricted mode
    if not auth_users:
        return True

    user_id = getattr(update.from_user, "id", None) if hasattr(update, "from_user") and update.from_user else None
    if user_id is not None and user_id in auth_users:
        return True

    return False


def is_owner(user_id_or_update: int | Message | CallbackQuery | None) -> bool:
    """Checks whether a user ID or Telegram update belongs to the bot OWNER.

    Priority:
    1. settings.owner_id (env OWNER_ID) if explicitly set.
    2. First user ID in settings.authorized_user_ids (env AUTHORIZED_USER_IDS[0]).
    """
    if user_id_or_update is None:
        return False

    if isinstance(user_id_or_update, (Message, CallbackQuery)):
        user_id = (
            getattr(user_id_or_update.from_user, "id", None)
            if hasattr(user_id_or_update, "from_user") and user_id_or_update.from_user
            else None
        )
    else:
        user_id = user_id_or_update

    if not user_id:
        return False

    if settings.owner_id is not None:
        return user_id == settings.owner_id

    if settings.authorized_user_ids:
        return user_id == settings.authorized_user_ids[0]

    return False


is_authorized_user_or_chat = is_authorized_user


async def _authorized_check_func(_, __, update: Message | CallbackQuery) -> bool:
    return is_authorized_user(update)


authorized_filter = filters.create(_authorized_check_func, name="AuthorizedFilter")


def check_auth_on_startup() -> None:
    """Logs a loud warning if the bot is running in unrestricted mode."""
    if not settings.authorized_user_ids:
        log.warning(
            "========================================================================\n"
            "⚠️ WARNING: AUTHORIZED_USER_IDS IS NOT CONFIGURED!\n"
            "   The bot is running in UNRESTRICTED / PUBLIC mode.\n"
            "   ANY Telegram user can issue commands and consume bot host resources.\n"
            "========================================================================"
        )


def register_unauthorized_rejection_handler(app: Client) -> None:
    """Registers fallback handlers that send a polite rejection message to unauthorized users."""

    @app.on_message(~authorized_filter, group=100)
    async def reject_unauthorized_message(_, message: Message) -> None:
        if message.text or message.caption:
            try:
                await message.reply_text("You are not authorized to use this bot.")
            except Exception:
                pass

    @app.on_callback_query(~authorized_filter, group=100)
    async def reject_unauthorized_callback(_, query: CallbackQuery) -> None:
        try:
            await query.answer("You are not authorized to use this bot.", show_alert=True)
        except Exception:
            pass
