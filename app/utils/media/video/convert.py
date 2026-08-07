from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import av

log = logging.getLogger(__name__)


def _remux(input_path: Path, output_path: Path, output_format: str = "mp4") -> bool:
    """Try remuxing (fast stream copy) into the specified container format."""
    try:
        log.info(
            "Attempting PyAV fast stream copy (remuxing) %s → %s (format=%s)",
            input_path.name, output_path.name, output_format,
        )
        with (
            av.open(str(input_path)) as input_container,
            av.open(str(output_path), mode="w", format=output_format) as output_container,
        ):
            streams_map = {}
            for stream in input_container.streams:
                if stream.type in ("video", "audio"):
                    try:
                        try:
                            out_stream = output_container.add_stream_from_template(stream)
                        except (AttributeError, TypeError):
                            out_stream = output_container.add_stream(template=stream)
                        out_stream.time_base = stream.time_base
                        streams_map[stream.index] = out_stream
                    except Exception as e:
                        log.warning("Could not copy stream %s: %s", stream, e)

            if not streams_map:
                raise ValueError("No copyable video/audio streams found")

            for packet in input_container.demux():
                if packet.stream.index not in streams_map:
                    continue
                if packet.dts is None:
                    continue
                packet.stream = streams_map[packet.stream.index]
                output_container.mux(packet)

        log.info("Fast stream copy (remuxing) successful for %s", input_path.name)
        return True
    except Exception as remux_err:
        log.warning(
            "Fast stream copy failed for %s (format=%s): %s",
            input_path.name, output_format, remux_err,
        )
        output_path.unlink(missing_ok=True)
        return False


def _remux_or_transcode(input_path: Path, output_path: Path) -> bool:
    """Remux video to MP4, falling back to MKV if MP4 muxing is incompatible.

    MKV (Matroska) accepts virtually any codec and is playable in Telegram.
    """
    if _remux(input_path, output_path):
        return True

    mkv_output = output_path.with_suffix(".mkv")
    log.info(
        "MP4 remux failed for %s — retrying with Matroska (.mkv) container",
        input_path.name,
    )
    return _remux(input_path, mkv_output, output_format="matroska")


async def convert_video_async(input_path: Path, output_path: Path) -> bool:
    """Asynchronously remux video to a Telegram-compatible container using PyAV.

    Tries MP4 first, falls back to MKV if MP4 remux fails.
    """
    return await asyncio.to_thread(_remux_or_transcode, input_path, output_path)
