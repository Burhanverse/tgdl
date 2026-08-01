from __future__ import annotations

import asyncio
from pathlib import Path

def is_photo_invalid_for_telegram(file_path: Path) -> bool:
    try:
        import PIL.Image
        with PIL.Image.open(file_path) as img:
            if img.mode in ("CMYK", "P", "1"):
                return True
            w, h = img.size
            if w <= 0 or h <= 0:
                return True
            if w + h > 10000 or max(w, h) > 9900:
                return True
            ratio = w / h if h > 0 else 0.0
            if ratio > 15.0 or ratio < (1.0 / 15.0):
                return True
    except Exception:
        return True
    return False

async def is_photo_invalid_for_telegram_async(file_path: Path) -> bool:
    return await asyncio.to_thread(is_photo_invalid_for_telegram, file_path)
