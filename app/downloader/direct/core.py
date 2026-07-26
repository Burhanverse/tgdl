from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional, Union
from urllib.parse import unquote, urlparse

import aiohttp
from aiofiles import open as aiopen

log = logging.getLogger(__name__)

_CHUNK_SIZE = 1024 * 1024  # 1MB chunks


class DirectDownloadError(Exception):
    pass


DIRECT_FILE_EXTENSIONS = {
    # Video
    ".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv", ".3gp", ".m4v", ".ts", ".f4v", ".vob",
    # Audio
    ".mp3", ".flac", ".m4a", ".aac", ".opus", ".ogg", ".wav", ".wma", ".alac", ".aiff",
    # Archives & Compressed
    ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso", ".tgz", ".tbz2", ".zst", ".cab", ".dmg",
    # Executables & Packages
    ".apk", ".exe", ".bin", ".msi", ".deb", ".rpm", ".appimage", ".app", ".ipa",
    # Documents & Ebooks
    ".pdf", ".epub", ".mobi", ".djvu", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
}


def is_direct_url(url: str) -> bool:
    """Determines if a URL is a direct file download link based on scheme or extension."""
    if not url:
        return False
    if url.startswith("direct:"):
        return True
    try:
        urls = []
        if url.startswith("[") and url.endswith("]"):
            try:
                parsed = json.loads(url)
                if isinstance(parsed, list):
                    urls = [str(u).strip() for u in parsed if str(u).strip()]
            except Exception:
                pass
        if not urls:
            urls = [u.strip() for u in url.split() if u.strip().startswith(("http://", "https://"))]

        for u in urls:
            clean_u = u.split("?", 1)[0].split("#", 1)[0]
            parsed = urlparse(clean_u)
            path_ext = Path(parsed.path).suffix.lower()
            if path_ext in DIRECT_FILE_EXTENSIONS:
                return True
    except Exception:
        pass
    return False


def get_filename_from_url(url: str, headers: Optional[Dict[str, str]] = None) -> str:
    """Extract filename from Content-Disposition header or URL path."""
    if headers:
        cd = headers.get("Content-Disposition") or headers.get("content-disposition")
        if cd:
            filenames = re.findall(r'filename\*?=(?:["\']?([^"\';]+)["\']?|UTF-8\'\'([^"\';]+))', cd, re.IGNORECASE)
            if filenames:
                fn = filenames[0][1] or filenames[0][0]
                if fn:
                    return unquote(fn).strip()

    parsed = urlparse(url)
    filename = Path(parsed.path).name
    filename = unquote(filename).strip()
    if not filename or filename in ("/", "\\"):
        filename = f"direct_file_{int(time.time())}.bin"
    return filename


class DirectDownloader:
    """
    Direct link / HTTP downloader inspired by mirror-leech-telegram-bot's DirectListener & direct_downloader.py.
    """

    def __init__(
        self,
        dest_dir: Path,
        progress_cb: Optional[Callable[[int, int, str], Coroutine[None, None, None]]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self.dest_dir = dest_dir
        self.progress_cb = progress_cb
        self.custom_headers = headers or {}

        self.processed_bytes = 0
        self.total_bytes = 0
        self.start_time = time.time()
        self.is_downloading = False
        self.is_cancelled = False
        self.failed_count = 0
        self.downloaded_files: List[Path] = []
        self.current_filename = ""

    @property
    def speed(self) -> float:
        elapsed = time.time() - self.start_time
        if elapsed > 0:
            return self.processed_bytes / elapsed
        return 0.0

    def cancel(self) -> None:
        self.is_cancelled = True

    async def _download_content_item(
        self,
        session: aiohttp.ClientSession,
        url: str,
        filename: Optional[str] = None,
        subpath: Optional[str] = None,
    ) -> Path:
        if self.is_cancelled:
            raise asyncio.CancelledError("Download cancelled before starting item.")

        save_dir = self.dest_dir
        if subpath:
            save_dir = save_dir / subpath
        save_dir.mkdir(parents=True, exist_ok=True)

        req_headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}
        req_headers.update(self.custom_headers)

        async with session.get(url, headers=req_headers, allow_redirects=True) as resp:
            if resp.status >= 400:
                raise DirectDownloadError(f"HTTP {resp.status} - {resp.reason}")

            if not filename:
                filename = get_filename_from_url(url, dict(resp.headers))

            self.current_filename = filename
            out_file = save_dir / filename

            file_size = 0
            if "Content-Length" in resp.headers:
                try:
                    file_size = int(resp.headers["Content-Length"])
                except Exception:
                    file_size = 0

            self.total_bytes += file_size
            item_processed = 0

            log.info("Downloading direct link %s to %s (size: %s bytes)", url, out_file, file_size)

            async with aiopen(out_file, "wb") as f:
                async for chunk in resp.content.iter_chunked(_CHUNK_SIZE):
                    if self.is_cancelled:
                        if out_file.exists():
                            out_file.unlink(missing_ok=True)
                        raise asyncio.CancelledError("Download cancelled during file stream.")

                    await f.write(chunk)
                    chunk_len = len(chunk)
                    item_processed += chunk_len
                    self.processed_bytes += chunk_len

                    if self.progress_cb:
                        try:
                            await self.progress_cb(self.processed_bytes, self.total_bytes, filename)
                        except Exception as e:
                            log.debug("Progress callback error: %s", e)

            return out_file

    async def download(
        self,
        contents: Union[str, List[Dict[str, str]]],
    ) -> List[Path]:
        """
        Download direct link(s).
        `contents` can be a single URL string or a list of content dicts:
        `[{"url": "...", "filename": "...", "path": "..."}, ...]`
        """
        self.is_downloading = True
        self.start_time = time.time()
        self.dest_dir.mkdir(parents=True, exist_ok=True)

        items: List[Dict[str, str]] = []
        if isinstance(contents, str):
            try:
                parsed = json.loads(contents)
                if isinstance(parsed, list):
                    for u in parsed:
                        if isinstance(u, str) and u.strip():
                            items.append({"url": u.strip(), "filename": "", "path": ""})
            except Exception:
                pass

            if not items:
                lines = [u.strip() for u in contents.split() if u.strip().startswith(("http://", "https://"))]
                if len(lines) > 1:
                    for u in lines:
                        items.append({"url": u, "filename": "", "path": ""})
                else:
                    items.append({"url": contents.strip(), "filename": "", "path": ""})
        elif isinstance(contents, list):
            for c in contents:
                if isinstance(c, dict) and "url" in c:
                    items.append({
                        "url": c["url"],
                        "filename": c.get("filename", ""),
                        "path": c.get("path", ""),
                    })
                elif isinstance(c, str) and c.strip():
                    items.append({"url": c.strip(), "filename": "", "path": ""})

        if not items:
            raise DirectDownloadError("No direct URLs provided for download.")

        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=None, connect=30.0)
        ) as session:
            for item in items:
                if self.is_cancelled:
                    break
                try:
                    downloaded_file = await self._download_content_item(
                        session=session,
                        url=item["url"],
                        filename=item.get("filename"),
                        subpath=item.get("path"),
                    )
                    self.downloaded_files.append(downloaded_file)
                except asyncio.CancelledError:
                    log.info("Direct download cancelled by user.")
                    raise
                except Exception as e:
                    self.failed_count += 1
                    log.error("Failed to download direct item %s: %s", item.get("url"), e)

        self.is_downloading = False
        if self.failed_count == len(items) and len(items) > 0:
            raise DirectDownloadError(f"All {len(items)} direct file downloads failed.")

        return self.downloaded_files


async def download_direct(
    url_or_contents: Union[str, List[Dict[str, str]]],
    dest_dir: Path,
    progress_cb: Optional[Callable[[int, int, str], Coroutine[None, None, None]]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> List[Path]:
    """Helper function to execute direct link download."""
    downloader = DirectDownloader(dest_dir=dest_dir, progress_cb=progress_cb, headers=headers)
    return await downloader.download(url_or_contents)
