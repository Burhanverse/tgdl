from __future__ import annotations

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def get_help_content(page: str = "main") -> tuple[str, InlineKeyboardMarkup]:
    """Generates help text and inline keyboard markup for topic-wise paged view."""

    if page == "dl":
        text = (
            "**Topic: Direct & Gallery Downloads**\n\n"
            "**Commands:**\n"
            "• `/dl [flags] <url>` or `/direct [flags] <url>`\n"
            "> _Fast multi-connection direct HTTP/HTTPS file downloader via aria2c or direct HTTP streams._\n\n"
            "• `/gdl [flags] <url>` or `/gallerydl [flags] <url>`\n"
            "> _Download media albums, posts, and videos from 100+ sites via gallery-dl engine._\n\n"
            "• `/mega [flags] <mega_url>` or `/meganz [flags] <mega_url>`\n"
            "> _Download files and folders recursively from mega.nz with real-time speed & file metrics._\n\n"
            "• `/mega -login <email:password>` or `/mega -logout` or `/mega -account`\n"
            "> _Log into your personal MEGA account, manage credentials, or view status._\n\n"
            "• `/m [-tg] <url>` or `/mirror [-tg] <url>`\n"
            "> _Download and mirror link or Telegram media file to server storage (use `-tg` to re-upload to Telegram)._\n\n"
            "**Supported Flags:**\n"
            "• `-m` or `-mirror`: Enable mirror mode.\n"
            "• `-tg`: Force re-upload to Telegram.\n"
            "• `-uz` or `-unzip`: Automatically extract downloaded archives.\n"
            "• `-p <password>` or `-pass <password>`: Specify extraction password.\n\n"
            "**Batch Processing:**\n"
            "• Reply to a `.txt` file containing URLs (one per line) with `/dl`, `/gdl`, or `/mega`."

        )
    elif page == "tor":
        text = (
            "**Topic: Torrent Downloads & Search Engine**\n\n"
            "**Commands:**\n"
            "• `/tor <magnet/url>` or reply to a `.torrent` file\n"
            "> _Download torrents or magnet links headlessly with real-time peer count and speed stats._\n\n"
            "• `/ts <query>` or `/torsearch <query>` or `/search <query>`\n"
            "> _Interactive multi-provider torrent search engine (Apibay/PirateBay, Torrents-CSV, Nyaa, YTS, TorrentGalaxy, LimeTorrents, Prowlarr)._\n\n"

            "**Search Engine Features:**\n"
            "• Browse search results with inline pagination buttons.\n"
            "• One-click **Download with /tor** trigger directly from search results."
        )
    elif page == "unzip":
        text = (
            "**Topic: Archive Extraction & Volume Splitting**\n\n"
            "**Commands:**\n"
            "• `/unzip [password]` (Reply to archive)\n"
            "> _Extract `.zip`, `.rar`, `.7z`, `.tar`, `.gz`, etc. archives directly to Telegram._\n\n"
            "• `/unzip split [password]`\n"
            "> _Start an interactive collection session for multi-part split archives (`.001`, `.002`, `.part1.rar`)._\n\n"
            "• `/unzip multi [password]`\n"
            "> _Start a batch session to upload and unpack multiple archive files together._\n\n"
            "**Handling & Safeguards:**\n"
            "• **Password Protection**: Encrypted archives prompt interactively for passwords.\n"
            "• **Volume Limit Safeguards**: Prompts user to split files exceeding Telegram's 2GB upload limit into sub-2GB volumes."
        )
    elif page == "cloud":
        text = (
            "**Topic: Cloud Storage & Upload Keys**\n\n"
            "**Google Drive:**\n"
            "• `/gd2tg <gdrive_link>`\n"
            "> _Download Google Drive files or folders directly to Telegram._\n"
            "> _Supports per-user Service Accounts (`auth/<user_id>/accounts/*.json`) and OAuth tokens (`token.json`)._\n\n"
            "**External Cloud Uploaders & Per-User Keys:**\n"
            "• `/pdup` (Reply to media)\n"
            "> _Upload Telegram media file directly to Pixeldrain._\n\n"
            "• `/gfup` or `/gofile` (Reply to media)\n"
            "> _Upload Telegram media file directly to GoFile._\n\n"
            "• `/fdup` or `/fileditch` (Reply to media)\n"
            "> _Upload Telegram media file directly to FileDitch._\n\n"
            "• `/gofilekey <token>` or `/gofilekey del`\n"
            "> _Set, view, or remove your personal GoFile API token._\n\n"
            "• `/pdkey <key>` or `/pdkey del`\n"
            "> _Set, view, or remove your personal Pixeldrain API key._"
        )
    elif page == "config":
        text = (
            "**Topic: Configuration & Task Management**\n\n"
            "**Commands:**\n"
            "• `/gdlconf` or `/gdl_config`\n"
            "> _Manage per-user `gallery-dl.conf` and `cookies.txt` for auth-protected or subscriber-only sites._\n"
            "> _Reply to `.conf` or `cookies.txt` with `/gdlconf` to upload (sanitized against dangerous postprocessor commands)._\n\n"
            "• `/status [user_id | me]`\n"
            "> _Real-time task dashboard showing speeds, progress bars, active downloads/uploads, queue, overview, and pagination._\n\n"
            "• `/cancel [job_id]`\n"
            "> _Cancel an active or queued job by ID or choose from an interactive job list._"
        )
    else:  # main page
        text = (
            "**TGDL Bot Documentation & Help Center**\n"
            "> _High-performance media downloader, cloud mirror, archive extractor, and torrent manager for Telegram._\n\n"
            "**Quick Start Guide:**\n"
            "• Send or paste any direct URL, magnet link, or file into chat to start processing.\n"
            "• Select a topic below to view detailed command syntax, flags, and usage instructions.\n\n"
            "**Available Topics:**\n"
            "• **Downloads**: Direct HTTP, Gallery-dl, and Mirror options.\n"
            "• **Torrents**: Magnet links, torrent files, and interactive Torrent Search.\n"
            "• **Archives**: Decompression, multi-part split sessions, and password handling.\n"
            "• **Cloud & Drive**: Google Drive downloads and direct uploads to Pixeldrain, GoFile, FileDitch.\n"
            "• **Config & Status**: Per-user cookies/config, task manager, and cancellation."
        )

    buttons = []
    if page == "main":
        buttons = [
            [
                InlineKeyboardButton("Downloads", callback_data="help_page:dl"),
                InlineKeyboardButton("Torrents", callback_data="help_page:tor"),
            ],
            [
                InlineKeyboardButton("Archives", callback_data="help_page:unzip"),
                InlineKeyboardButton("Cloud & Drive", callback_data="help_page:cloud"),
            ],
            [
                InlineKeyboardButton("Config & Status", callback_data="help_page:config"),
                InlineKeyboardButton("Close", callback_data="help_page:close"),
            ],
        ]
    else:
        buttons = [
            [
                InlineKeyboardButton("Downloads", callback_data="help_page:dl"),
                InlineKeyboardButton("Torrents", callback_data="help_page:tor"),
                InlineKeyboardButton("Archives", callback_data="help_page:unzip"),
            ],
            [
                InlineKeyboardButton("Cloud & Drive", callback_data="help_page:cloud"),
                InlineKeyboardButton("Config & Status", callback_data="help_page:config"),
            ],
            [
                InlineKeyboardButton("Main Menu", callback_data="help_page:main"),
                InlineKeyboardButton("Close", callback_data="help_page:close"),
            ],
        ]

    return text, InlineKeyboardMarkup(buttons)
