from __future__ import annotations

import logging
from pathlib import Path

from ...utils.media import VIDEO_EXT, split_binary, split_video_async

log = logging.getLogger(__name__)


async def split_video(video_path: Path, max_size_bytes: int) -> list[Path]:
    try:
        parts = await split_video_async(video_path, max_size_bytes)
        if parts:
            return parts
    except Exception:
        log.exception("Failed to split video using PyAV segmenter: %s", video_path.name)

    return await split_binary(video_path, max_size_bytes)


async def handle_large_file(path: Path, split_large_files: bool) -> list[Path]:
    max_size = int(1.95 * 1024 * 1024 * 1024)
    size = path.stat().st_size
    if size <= max_size:
        return [path]

    log.info("File '%s' size is %s bytes, exceeds 1.95GB threshold", path.name, size)
    if not split_large_files:
        log.info("split_large_files is False; deleting and skipping '%s'", path.name)
        try:
            path.unlink()
        except Exception:
            # expected: skipped large file already unlinked
            pass
        return []

    log.info("split_large_files is True; splitting '%s'", path.name)
    ext = path.suffix.lower()
    if ext in VIDEO_EXT:
        parts = await split_video(path, max_size)
    else:
        parts = await split_binary(path, max_size)

    if parts:
        log.info("Successfully split '%s' into %s parts", path.name, len(parts))
        try:
            path.unlink()
        except Exception:
            # expected: original large file already unlinked after split
            pass
        return parts
    else:
        log.error("Failed to split '%s'; deleting to avoid loop", path.name)
        try:
            path.unlink()
        except Exception:
            # expected: failed split file already unlinked
            pass
        return []
