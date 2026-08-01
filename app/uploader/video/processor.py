from __future__ import annotations

import asyncio
import logging
import random
import tempfile
from pathlib import Path

import av
from PIL import Image

log = logging.getLogger(__name__)

def _probe_video_sync(video_path: Path) -> dict[str, Any]:
    info: dict[str, Any] = {"decodable": False}
    try:
        with av.open(str(video_path)) as container:
            stream = next((s for s in container.streams if s.type == "video"), None)
            if stream:
                info["width"] = stream.width
                info["height"] = stream.height
                if stream.duration and stream.time_base:
                    info["duration"] = int(round(float(stream.duration * stream.time_base)))
                elif container.duration:
                    info["duration"] = int(round(container.duration / 1000000.0))

                try:
                    for _ in container.decode(stream):
                        info["decodable"] = True
                        break
                except Exception:
                    info["decodable"] = False
    except Exception as e:
        log.exception("PyAV failed to probe video %s: %s", video_path.name, e)
    return info

async def probe_video(video_path: Path) -> dict[str, Any]:
    """Asynchronously probe video metadata using PyAV."""
    return await asyncio.to_thread(_probe_video_sync, video_path)

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

def _take_screenshots_sync(video_path: Path, duration: int) -> list[Path]:
    if duration <= 0:
        return []

    timestamps = sorted([random.uniform(0.05 * duration, 0.95 * duration) for _ in range(9)])
    screenshots: list[Path] = []
    consecutive_failures = 0

    # Open/close container for each screenshot to ensure absolute robustness and prevent seek issues
    for idx, ts in enumerate(timestamps):
        success = False
        err_msg: Any = "No video stream"
        try:
            with av.open(str(video_path)) as container:
                stream = next((s for s in container.streams if s.type == "video"), None)
                if stream:
                    target_pts = int(ts / stream.time_base)
                    try:
                        container.seek(target_pts, stream=stream)
                    except Exception:
                        # expected: video container seek fallback to start
                        pass

                    err_msg = "No frame decoded"
                    for frame in container.decode(stream):
                        img = frame.to_image()
                        shot_path = Path(tempfile.gettempdir()) / f"{video_path.stem}_screenshot_{idx}.jpg"
                        img.save(shot_path, "JPEG", quality=80)
                        screenshots.append(shot_path)
                        success = True
                        break
        except Exception as e:
            err_msg = e

        if success:
            consecutive_failures = 0
        else:
            consecutive_failures += 1
            if consecutive_failures >= 3:
                log.warning(
                    "Aborting screenshot capture for %s after %d consecutive decode failures — file may be corrupt or incomplete",
                    video_path.name,
                    consecutive_failures,
                )
                break
            log.warning("PyAV failed to capture screenshot at %s for %s: %s", ts, video_path.name, err_msg)

    return screenshots

async def take_screenshots(video_path: Path, duration: int) -> list[Path]:
    """Asynchronously take 9 random screenshots from the video using PyAV and Pillow."""
    return await asyncio.to_thread(_take_screenshots_sync, video_path, duration)
