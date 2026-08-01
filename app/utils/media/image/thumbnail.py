from __future__ import annotations

import asyncio
import logging
from pathlib import Path

log = logging.getLogger(__name__)

def _make_image_thumbnail(file_path: Path) -> Path | None:
    try:
        import PIL.Image
        thumb_path = file_path.with_name(f"thumb_{file_path.stem}.jpg")
        with PIL.Image.open(file_path) as img:
            img.thumbnail((320, 320))
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img.save(thumb_path, "JPEG", quality=85)
        return thumb_path
    except Exception as e:
        log.debug("Failed to create image thumbnail for %s: %s", file_path.name, e)
        return None

async def extract_image_thumbnail(file_path: Path) -> Path | None:
    return await asyncio.to_thread(_make_image_thumbnail, file_path)
