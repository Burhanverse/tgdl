from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import filetype

log = logging.getLogger(__name__)

_GENERIC_EXTENSIONS = {".bin", ".tmp", ".part", ".download", ""}

# Explicit mapping from filetype guessed .extension to canonical project extensions
_EXTENSION_MAP: dict[str, str] = {
    # Images
    "jpg": ".jpg",
    "jpeg": ".jpg",
    "png": ".png",
    "webp": ".webp",
    "gif": ".gif",
    "bmp": ".bmp",
    "tiff": ".tiff",
    "tif": ".tiff",
    "heic": ".heic",
    "heif": ".heif",
    "ico": ".ico",
    # Videos
    "mp4": ".mp4",
    "m4v": ".m4v",
    "mkv": ".mkv",
    "webm": ".webm",
    "mov": ".mov",
    "avi": ".avi",
    "wmv": ".wmv",
    "flv": ".flv",
    "3gp": ".3gp",
    "mpg": ".mpg",
    "mpeg": ".mpg",
    "ts": ".ts",
    "tts": ".ts",
    "f4v": ".f4v",
    "vob": ".vob",
    # Audio
    "mp3": ".mp3",
    "flac": ".flac",
    "m4a": ".m4a",
    "aac": ".aac",
    "opus": ".opus",
    "ogg": ".ogg",
    "wav": ".wav",
    "wma": ".wma",
    "alac": ".alac",
    "aiff": ".aiff",
    # Archives
    "zip": ".zip",
    "7z": ".7z",
    "rar": ".rar",
    "tar": ".tar",
    "gz": ".gz",
    "bz2": ".bz2",
    "xz": ".xz",
    "cab": ".cab",
    "iso": ".iso",
    "deb": ".deb",
    "ar": ".ar",
    "cpio": ".cpio",
    "rpm": ".rpm",
    "zst": ".zst",
    # Documents
    "pdf": ".pdf",
}


def detect_extension(path: Path) -> str | None:
    """Use filetype magic bytes to detect canonical file extension."""
    if not path.is_file():
        return None
    try:
        kind = filetype.guess(str(path))
        if kind is None or not kind.extension:
            return None
        ext_clean = kind.extension.lower()
        return _EXTENSION_MAP.get(ext_clean, f".{ext_clean}")
    except Exception as e:
        log.debug("Magic byte detection failed for %s: %s", path.name, e)
        return None


def needs_extension_fix(path: Path) -> bool:
    """Return True if path has a generic or missing extension."""
    return path.suffix.lower() in _GENERIC_EXTENSIONS


async def ensure_extension(path: Path) -> Path:
    """Detect and repair generic/missing extensions for settled files."""
    if not path.is_file() or not needs_extension_fix(path):
        return path

    detected_ext = await asyncio.to_thread(detect_extension, path)
    if not detected_ext:
        return path

    if path.suffix.lower() == detected_ext.lower():
        return path

    stem = path.stem if path.suffix else path.name
    target = path.with_name(f"{stem}{detected_ext}")

    if target.exists() and target != path:
        counter = 1
        while True:
            candidate = path.with_name(f"{stem}_{counter}{detected_ext}")
            if not candidate.exists():
                target = candidate
                break
            counter += 1

    try:
        path.rename(target)
        log.info("Renamed file with generic extension: %s -> %s", path.name, target.name)
        return target
    except Exception as e:
        log.warning("Failed to rename file %s to %s: %s", path.name, target.name, e)
        return path
