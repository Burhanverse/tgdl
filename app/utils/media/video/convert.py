from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import av

log = logging.getLogger(__name__)

def _remux_or_transcode(input_path: Path, output_path: Path) -> bool:
    # 1. Try remuxing (fast stream copy)
    try:
        log.info("Attempting PyAV fast stream copy (remuxing) for %s to %s", input_path.name, output_path.name)
        with av.open(str(input_path)) as input_container, av.open(str(output_path), mode="w", format="mp4") as output_container:
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
                # Assign to output stream
                packet.stream = streams_map[packet.stream.index]
                output_container.mux(packet)

        log.info("Fast stream copy (remuxing) successful for %s", input_path.name)
        return True
    except Exception as remux_err:
        log.warning("Fast stream copy failed for %s: %s. Falling back to full transcoding.", input_path.name, remux_err)
        output_path.unlink(missing_ok=True)

    # 2. Try transcoding fallback (H.264 + AAC)
    try:
        log.info("Starting PyAV transcoding fallback for %s to %s", input_path.name, output_path.name)
        with av.open(str(input_path)) as input_container, av.open(str(output_path), mode="w", format="mp4") as output_container:
            in_video = next((s for s in input_container.streams if s.type == "video"), None)
            in_audio = next((s for s in input_container.streams if s.type == "audio"), None)

            out_video = None
            out_audio = None

            if in_video:
                # Add libx264 video stream
                # Default to 30 fps if rate is not set
                fps = in_video.average_rate if in_video.average_rate else 30
                out_video = output_container.add_stream("libx264", rate=fps)
                out_video.width = in_video.width
                out_video.height = in_video.height
                out_video.pix_fmt = "yuv420p"
                out_video.options = {"preset": "superfast", "crf": "18"}

            if in_audio:
                # Add AAC audio stream
                rate = in_audio.rate if in_audio.rate else 44100
                out_audio = output_container.add_stream("aac", rate=rate)
                if in_audio.channels:
                    out_audio.channels = in_audio.channels
                if in_audio.layout:
                    out_audio.layout = in_audio.layout

            if not out_video and not out_audio:
                raise ValueError("No video or audio stream to transcode")

            # Decode and encode frame-by-frame
            for frame in input_container.decode():
                if isinstance(frame, av.VideoFrame) and out_video:
                    # Let encoder automatically compute timestamps
                    frame.pts = None
                    frame.time_base = None
                    for packet in out_video.encode(frame):
                        output_container.mux(packet)
                elif isinstance(frame, av.AudioFrame) and out_audio:
                    frame.pts = None
                    frame.time_base = None
                    for packet in out_audio.encode(frame):
                        output_container.mux(packet)

            # Flush encoders
            if out_video:
                for packet in out_video.encode():
                    output_container.mux(packet)
            if out_audio:
                for packet in out_audio.encode():
                    output_container.mux(packet)

        log.info("Transcoding successful for %s", input_path.name)
        return True
    except Exception as trans_err:
        log.exception("Transcoding failed for %s: %s", input_path.name, trans_err)
        output_path.unlink(missing_ok=True)
        return False

async def convert_video_async(input_path: Path, output_path: Path) -> bool:
    """Asynchronously convert video to MP4 container using PyAV."""
    return await asyncio.to_thread(_remux_or_transcode, input_path, output_path)
