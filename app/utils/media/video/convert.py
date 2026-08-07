from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import av

log = logging.getLogger(__name__)


def _remux_to_mkv(input_path: Path, output_path: Path) -> bool:
    """Remux (fast stream copy) input video directly to Matroska (.mkv) container."""
    mkv_output = output_path.with_suffix(".mkv")
    try:
        log.info(
            "Attempting PyAV fast stream copy (remuxing) %s → %s (format=matroska)",
            input_path.name, mkv_output.name,
        )
        with (
            av.open(str(input_path)) as input_container,
            av.open(str(mkv_output), mode="w", format="matroska") as output_container,
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

        log.info("Fast stream copy (remuxing) successful for %s → %s", input_path.name, mkv_output.name)
        return True
    except Exception as remux_err:
        log.warning("Fast stream copy failed for %s to MKV: %s", input_path.name, remux_err)
        mkv_output.unlink(missing_ok=True)
        return False


async def convert_video_async(input_path: Path, output_path: Path) -> bool:
    """Asynchronously remux video directly to Matroska (.mkv) container using PyAV."""
    return await asyncio.to_thread(_remux_to_mkv, input_path, output_path)
