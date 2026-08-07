from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import av

log = logging.getLogger(__name__)

_MAX_CONSECUTIVE_MUX_FAILURES = 20


class _EarlyMuxError(Exception):
    """Raised when mux() fails on the very first packets, triggering container-format fallback."""
    pass


def _split_video_pyav_sync(
    video_path: Path,
    max_size_bytes: int,
    output_format: str = "mp4",
    output_suffix: str | None = None,
) -> list[Path]:
    """Split a video at keyframe boundaries using PyAV stream copy.

    Args:
        video_path: Path to the source video.
        max_size_bytes: Maximum size per segment.
        output_format: Container format for av.open (e.g. "mp4", "matroska").
        output_suffix: File extension for output parts (e.g. ".mp4", ".mkv").
                       Defaults to video_path.suffix.
    """
    if output_suffix is None:
        output_suffix = video_path.suffix

    log.info(
        "Splitting video %s using PyAV segmenter (format=%s, suffix=%s)",
        video_path.name, output_format, output_suffix,
    )
    parts: list[Path] = []

    try:
        input_container = av.open(str(video_path))
    except Exception as e:
        log.exception("Failed to open video for splitting with PyAV: %s", e)
        return []

    # Find video stream to decide keyframes
    video_stream = next((s for s in input_container.streams if s.type == "video"), None)
    if not video_stream:
        input_container.close()
        log.warning("No video stream found for PyAV segmenter. Falling back.")
        return []

    part_num = 1
    current_segment_size = 0
    target_segment_size = int(max_size_bytes * 0.95)

    output_container = None
    streams_map = {}

    segment_start_times: dict[int, float] = {}
    last_muxed_dts: dict[int, int] = {}

    def open_next_segment():
        nonlocal part_num, output_container, streams_map, current_segment_size, segment_start_times, last_muxed_dts
        if output_container:
            output_container.close()

        part_path = video_path.parent / f"{video_path.stem}_part{part_num:03d}{output_suffix}"
        parts.append(part_path)

        output_container = av.open(str(part_path), mode="w", format=output_format)
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
                    log.warning("Could not add stream template: %s", e)

        part_num += 1
        current_segment_size = 0
        segment_start_times = {}
        last_muxed_dts = {}

    try:
        open_next_segment()

        successful_packets = 0
        skipped_packets = 0
        consecutive_failures = 0

        for packet in input_container.demux():
            if packet.stream.index not in streams_map:
                continue
            if packet.dts is None:
                continue

            # Check if we should split before writing a new keyframe package
            if (packet.stream.type == "video"
                and packet.is_keyframe
                and current_segment_size >= target_segment_size):
                log.info("Splitting at keyframe PTS %s, current segment size %s MB", packet.pts, current_segment_size / (1024 * 1024))
                open_next_segment()
                successful_packets = 0
                consecutive_failures = 0

            out_stream = streams_map[packet.stream.index]
            stream_idx = packet.stream.index

            # Sync start of segment to 0 per stream
            if stream_idx not in segment_start_times:
                if packet.pts is not None:
                    segment_start_times[stream_idx] = float(packet.pts * packet.stream.time_base)
                else:
                    segment_start_times[stream_idx] = 0.0

            baseline = segment_start_times[stream_idx]

            if packet.pts is not None:
                packet_time = float(packet.pts * packet.stream.time_base)
                rebased_pts = int((packet_time - baseline) / packet.stream.time_base)
                packet.pts = max(0, rebased_pts)
            if packet.dts is not None:
                packet_dts = float(packet.dts * packet.stream.time_base)
                rebased_dts = int((packet_dts - baseline) / packet.stream.time_base)
                packet.dts = max(0, rebased_dts)

            if packet.pts is not None and packet.dts is not None and packet.pts < packet.dts:
                packet.pts = packet.dts

            if packet.dts is not None:
                last_dts = last_muxed_dts.get(stream_idx)
                if last_dts is not None and packet.dts < last_dts:
                    log.warning(
                        "Dropping non-monotonic packet for stream %s: dts=%s < last_dts=%s",
                        stream_idx, packet.dts, last_dts
                    )
                    skipped_packets += 1
                    continue
                last_muxed_dts[stream_idx] = packet.dts

            packet.stream = out_stream

            try:
                output_container.mux(packet)
                successful_packets += 1
                consecutive_failures = 0
            except Exception as mux_err:
                consecutive_failures += 1
                skipped_packets += 1

                if successful_packets < 2:
                    log.warning(
                        "PyAV mux failed on early packet %d (format=%s) for %s: %s",
                        successful_packets, output_format, video_path.name, mux_err,
                    )
                    raise _EarlyMuxError(str(mux_err)) from mux_err

                if consecutive_failures >= _MAX_CONSECUTIVE_MUX_FAILURES:
                    log.error(
                        "Aborting PyAV split for %s: %d consecutive mux failures",
                        video_path.name, consecutive_failures,
                    )
                    raise

                log.warning(
                    "Skipping packet mux error for stream %s pts=%s dts=%s: %s",
                    stream_idx, packet.pts, packet.dts, mux_err,
                )
                continue

            # Update accumulated size
            current_segment_size += packet.size

        if output_container:
            output_container.close()

        if skipped_packets:
            log.info(
                "PyAV split of %s completed with %d packets skipped due to mux errors",
                video_path.name, skipped_packets,
            )

    except _EarlyMuxError:
        # Let this propagate so the caller can retry with a different format
        if output_container:
            try:
                output_container.close()
            except Exception:
                pass
        for p in parts:
            p.unlink(missing_ok=True)
        raise
    except Exception as e:
        log.exception("Error during PyAV video splitting: %s", e)
        if output_container:
            try:
                output_container.close()
            except Exception:
                pass
        for p in parts:
            p.unlink(missing_ok=True)
        return []
    finally:
        input_container.close()

    return parts


def _split_video_with_fallback(video_path: Path, max_size_bytes: int) -> list[Path]:
    """Try splitting with the source container format first, then fall back to MKV.

    MP4 muxing via stream copy fails for certain codec profiles (e.g. some H.264
    high profiles, non-standard parameter sets). Matroska (MKV) accepts virtually
    any codec and is playable in Telegram, so it's used as the fallback container.
    """
    try:
        return _split_video_pyav_sync(video_path, max_size_bytes)
    except _EarlyMuxError:
        log.info(
            "MP4 mux failed early for %s — retrying with Matroska (.mkv) container",
            video_path.name,
        )

    # Retry with Matroska
    return _split_video_pyav_sync(
        video_path,
        max_size_bytes,
        output_format="matroska",
        output_suffix=".mkv",
    )


async def split_video_async(video_path: Path, max_size_bytes: int) -> list[Path]:
    """Asynchronously split a video using PyAV stream copier at keyframe boundaries.

    Tries the source format (MP4) first; on early mux failure, retries with
    Matroska (.mkv) which is more permissive with codec parameters.
    """
    return await asyncio.to_thread(_split_video_with_fallback, video_path, max_size_bytes)
