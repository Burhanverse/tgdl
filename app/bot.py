from __future__ import annotations

import asyncio
import logging
import logging.handlers
import time
from pathlib import Path

from pyrogram import Client, idle

from .config import settings
from .handlers import register_all_handlers
from .telegram_helper import delete_status

log = logging.getLogger("tgdl_bot")


def setup_logging() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    root = logging.getLogger()
    root.setLevel(level)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    file_handler = logging.handlers.RotatingFileHandler(
        settings.log_dir / "bot.log", maxBytes=10_000_000, backupCount=5
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    logging.getLogger("pyrogram").setLevel(logging.WARNING)


async def log_upload(job_id: int, filename: str) -> None:
    log_path = settings.log_dir / "uploads.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def append_to_file():
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - Job #{job_id} - Uploaded: {filename}\n")

    await asyncio.to_thread(append_to_file)


async def main() -> None:
    setup_logging()
    log.info("Starting TGDL Bot...")

    app = Client(
        "tgdl_bot",
        api_id=settings.tg_api_id,
        api_hash=settings.tg_api_hash,
        bot_token=settings.tg_bot_token,
        workdir=str(settings.data_dir),
    )
    register_all_handlers(app)

    await app.start()

    try:
        from pyrogram.types import BotCommand
        await app.set_bot_commands([
            BotCommand("m", "Mirror file/URL to GoFile, FileDitch & Pixeldrain"),
            BotCommand("mirror", "Mirror file/URL to GoFile, FileDitch & Pixeldrain"),
            BotCommand("direct", "Download direct HTTP link"),
            BotCommand("dl", "Download direct HTTP link"),
            BotCommand("tor", "Download torrent or magnet link"),
            BotCommand("gdl", "Batch download URLs from replied .txt file"),
            BotCommand("gdlconf", "Manage user gallery-dl configuration"),
            BotCommand("gd2tg", "Download Google Drive link to Telegram"),
            BotCommand("gfup", "Upload replied media to GoFile"),
            BotCommand("gofile", "Upload replied media to GoFile"),
            BotCommand("fdup", "Upload replied media to FileDitch"),
            BotCommand("fileditch", "Upload replied media to FileDitch"),
            BotCommand("pdup", "Upload replied media to Pixeldrain"),
            BotCommand("unzip", "Download & extract archive"),
            BotCommand("status", "Show active tasks & status"),
            BotCommand("cancel", "Cancel active or queued jobs"),
            BotCommand("help", "Show command help guide"),
            BotCommand("start", "Start bot & get welcome message"),
        ])
        log.info("Bot commands set successfully on Telegram.")
    except Exception as e:
        log.warning("Failed to set bot commands: %s", e)

    from .manager import queue_manager, store, cleanup_orphaned_directories
    await store.open()
    await cleanup_orphaned_directories()
    await queue_manager.start(app, store)

    log.info("Bot is active and listening for messages.")
    await idle()

    log.info("Shutting down bot...")
    await queue_manager.stop()
    await store.close()
    await delete_status()
    await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
