from __future__ import annotations

from pyrogram import Client

from ..auth import check_auth_on_startup, register_unauthorized_rejection_handler
from .base import register_base_handlers
from .status import register_status_handlers
from .cancel import register_cancel_handlers
from .download import register_download_handlers
from .unzip import register_unzip_handlers
from .callbacks import register_choice_callback_handlers
from .gdlconf import register_gdlconf_handlers
from .torrent_search import register_torrent_search_handlers


def register_all_handlers(app: Client) -> None:
    """Registers all command and callback query handlers on Pyrogram Client."""
    check_auth_on_startup()
    register_base_handlers(app)
    register_status_handlers(app)
    register_cancel_handlers(app)
    register_download_handlers(app)
    register_unzip_handlers(app)
    register_choice_callback_handlers(app)
    register_gdlconf_handlers(app)
    register_torrent_search_handlers(app)
    register_unauthorized_rejection_handler(app)


__all__ = ["register_all_handlers"]
