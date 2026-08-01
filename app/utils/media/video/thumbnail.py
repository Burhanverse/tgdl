from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path

import av
from PIL import Image

log = logging.getLogger(__name__)

def _extract_video_thumbnail_sync(video_path: Path) -> Path | None:
    thumb_path = Path(tempfile.gettempdir()) / f"{video_path.stem}_thumb.jpg"
    try:
        with av.open(str(video_path)) as container:
            stream = next((s for s in container.streams if s.type == "video"), None)
            if not stream:
                return None

            # Seek to 4.0 seconds or start of video
            target_sec = min(4.0, float(container.duration / 1000000.0) if container.duration else 0.0)
            target_pts = int(target_sec / stream.time_base)
            try:
                container.seek(target_pts, stream=stream)
            except Exception:
                # expected: video container seek fallback to start
                pass

            for frame in container.decode(stream):
                img = frame.to_image()
                w, h = img.size
                scale = 320 / w
                new_h = int(h * scale)
                img = img.resize((320, new_h), Image.Resampling.LANCZOS)
                img.save(thumb_path, "JPEG", quality=85)
                return thumb_path
    except Exception as e:
        log.exception("PyAV failed to extract video thumbnail for %s: %s", video_path.name, e)
        thumb_path.unlink(missing_ok=True)
    return None

async def extract_video_thumbnail(video_path: Path) -> Path | None:
    """Asynchronously extract video thumbnail using PyAV and Pillow."""
    return await asyncio.to_thread(_extract_video_thumbnail_sync, video_path)
