from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import av

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
