from .gallery_dl import run_with_progress, DownloadResult, GalleryDLNotFound
from .torrent import download_torrent_async, start_aria2_daemon, stop_aria2_daemon
from .direct import DirectDownloader, DirectDownloadError, download_direct, is_direct_url
from .telegram import TelegramDownloader, TelegramDownloadError, download_telegram_media

__all__ = [
    "run_with_progress",
    "DownloadResult",
    "GalleryDLNotFound",
    "download_torrent_async",
    "start_aria2_daemon",
    "stop_aria2_daemon",
    "DirectDownloader",
    "DirectDownloadError",
    "download_direct",
    "is_direct_url",
    "TelegramDownloader",
    "TelegramDownloadError",
    "download_telegram_media",
]
