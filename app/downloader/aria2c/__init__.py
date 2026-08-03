from .torrent import (
    DownloadResult,
    download_torrent_async,
    download_via_aria2_async,
    start_aria2_daemon,
    stop_aria2_daemon,
)

__all__ = [
    "DownloadResult",
    "download_torrent_async",
    "download_via_aria2_async",
    "start_aria2_daemon",
    "stop_aria2_daemon",
]
