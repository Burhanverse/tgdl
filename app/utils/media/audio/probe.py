from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import av

AUDIO_CONVERSION_EXT = {".wav", ".flac", ".ogg", ".opus", ".aiff", ".aac"}


def probe_audio(audio_path: Path) -> dict[str, Any]:
    info = {"duration": 0, "artist": "", "title": ""}
    try:
        with av.open(str(audio_path)) as container:
            if container.duration:
                info["duration"] = int(round(container.duration / 1000000.0))
            meta = container.metadata or {}
            info["artist"] = meta.get("artist") or meta.get("ARTIST") or ""
            info["title"] = meta.get("title") or meta.get("TITLE") or audio_path.stem
    except Exception as e:
        log.warning("PyAV failed to probe audio %s: %s", audio_path.name, e)
    return info

async def probe_audio_async(audio_path: Path) -> dict[str, Any]:
    return await asyncio.to_thread(probe_audio, audio_path)
