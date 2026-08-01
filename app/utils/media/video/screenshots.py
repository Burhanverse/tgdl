from __future__ import annotations

import asyncio
import logging
import random
import tempfile
from pathlib import Path
from typing import Any

import av
from PIL import Image

log = logging.getLogger(__name__)

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
