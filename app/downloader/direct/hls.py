"""
HLS (M3U8) downloader module for tgdl's DirectDownloader.

SSRF Note:
The top-level playlist URL is validated against `is_url_private_ip`.
However, once handed to `av.open()`, libavformat's native HLS demuxer fetches `.ts`
segment URLs internally without passing through tgdl's Python SSRF guard. This is a
known limitation for simplicity and speed.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Callable, Coroutine
from pathlib import Path
from urllib.parse import urljoin

import aiohttp
import av

from ...config import settings
from .core import DirectDownloadError, is_url_private_ip

log = logging.getLogger(__name__)


def parse_master_playlist(playlist_text: str, base_url: str) -> list[tuple[int, str]]:
    """
    Parses an M3U8 master playlist text to extract (bandwidth, variant_url) pairs.
    """
    variants: list[tuple[int, str]] = []
    lines = playlist_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXT-X-STREAM-INF"):
            bandwidth = 0
            bw_match = re.search(r"BANDWIDTH=(\d+)", line)
            if bw_match:
                bandwidth = int(bw_match.group(1))

            # Find next non-empty, non-comment line for URI
            i += 1
            while i < len(lines):
                uri_line = lines[i].strip()
                if uri_line and not uri_line.startswith("#"):
                    variant_url = urljoin(base_url, uri_line)
                    variants.append((bandwidth, variant_url))
                    break
                i += 1
        i += 1
    return variants


def calculate_playlist_duration(playlist_text: str) -> float:
    """
    Parses #EXTINF segment durations from a media playlist text and returns total duration in seconds.
    """
    durations = re.findall(r"#EXTINF:([0-9.]+)", playlist_text)
    total = 0.0
    for d in durations:
        try:
            total += float(d)
        except ValueError:
            pass
    return total


async def download_hls(
    url: str,
    dest_path: Path,
    headers: dict[str, str] | None = None,
    progress_cb: Callable[[float, float, str, str], Coroutine[None, None, None]] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    quality: str = "best",
) -> Path:
    """
    Download an HLS (.m3u8) video stream and remux it into a single MP4 container using PyAV.
    """
    if is_cancelled and is_cancelled():
        raise asyncio.CancelledError("Download cancelled before starting HLS fetch.")

    if not settings.allow_private_network_urls:
        if await is_url_private_ip(url):
            log.warning("SSRF protection blocked HLS URL %s (resolves to private/reserved IP)", url)
            raise DirectDownloadError(f"Access to private/internal network URL '{url}' is prohibited.")

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    part_file = dest_path.parent / f"{dest_path.name}.part"

    req_headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}
    if headers:
        req_headers.update(headers)

    # Fetch initial playlist
    log.info("Fetching M3U8 playlist from %s", url)
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=30.0, connect=15.0)
    ) as session:
        async with session.get(url, headers=req_headers, allow_redirects=True) as resp:
            if resp.status >= 400:
                raise DirectDownloadError(f"HTTP {resp.status} - {resp.reason} when fetching playlist")
            content = await resp.text()
            final_url = str(resp.url)

    # Check if master playlist
    media_url = final_url
    media_content = content

    if "#EXT-X-STREAM-INF" in content:
        variants = parse_master_playlist(content, final_url)
        if not variants:
            raise DirectDownloadError("Master playlist found, but failed to parse variant streams.")

        # Sort variants by bandwidth
        variants.sort(key=lambda x: x[0])
        if quality == "worst":
            chosen_bw, media_url = variants[0]
        else:
            chosen_bw, media_url = variants[-1]

        log.info("Selected HLS variant URL (bandwidth: %s): %s", chosen_bw, media_url)

        # SSRF check on chosen media URL
        if not settings.allow_private_network_urls:
            if await is_url_private_ip(media_url):
                log.warning("SSRF protection blocked variant HLS URL %s", media_url)
                raise DirectDownloadError(f"Access to private/internal network URL '{media_url}' is prohibited.")

        # Fetch media playlist
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30.0, connect=15.0)
        ) as session:
            async with session.get(media_url, headers=req_headers, allow_redirects=True) as resp:
                if resp.status >= 400:
                    raise DirectDownloadError(f"HTTP {resp.status} - {resp.reason} when fetching media playlist")
                media_content = await resp.text()

    # VOD vs Live check
    if "#EXT-X-ENDLIST" not in media_content:
        raise DirectDownloadError("Live HLS streams are not supported — only VOD (finite) playlists can be downloaded.")

    total_duration_seconds = calculate_playlist_duration(media_content)
    log.info("Starting HLS remuxing for %s (total duration: %.2fs)", dest_path.name, total_duration_seconds)

    header_str = "".join(f"{k}: {v}\r\n" for k, v in req_headers.items())
    pyav_options = {"headers": header_str}

    loop = asyncio.get_running_loop()

    def _do_remux() -> None:
        try:
            with av.open(media_url, options=pyav_options) as input_container:
                with av.open(str(part_file), mode="w") as output_container:
                    streams_map = {}
                    main_stream_index = None
                    main_time_base = None

                    for stream in input_container.streams:
                        if stream.type in ("video", "audio"):
                            try:
                                try:
                                    out_stream = output_container.add_stream_from_template(stream)
                                except (AttributeError, TypeError):
                                    out_stream = output_container.add_stream(template=stream)
                                out_stream.time_base = stream.time_base
                                streams_map[stream.index] = out_stream
                                if stream.type == "video" and main_stream_index is None:
                                    main_stream_index = stream.index
                                    main_time_base = stream.time_base
                            except Exception as e:
                                log.warning("Could not copy HLS stream %s: %s", stream, e)

                    if not streams_map:
                        raise DirectDownloadError("No copyable video or audio streams found in HLS playlist.")

                    if main_stream_index is None:
                        first_idx = next(iter(streams_map.keys()))
                        main_stream_index = first_idx
                        main_time_base = input_container.streams[first_idx].time_base

                    packet_count = 0
                    last_progress_time = 0.0

                    for packet in input_container.demux():
                        packet_count += 1
                        if packet_count % 50 == 0:
                            if is_cancelled and is_cancelled():
                                raise asyncio.CancelledError("HLS download cancelled.")

                        if packet.stream.index not in streams_map or packet.dts is None:
                            continue

                        if packet.stream.index == main_stream_index and packet.pts is not None and main_time_base is not None:
                            elapsed_seconds = float(packet.pts * main_time_base)
                            now = time.time()
                            if now - last_progress_time >= 1.0:
                                last_progress_time = now
                                if progress_cb:
                                    try:
                                        asyncio.run_coroutine_threadsafe(
                                            progress_cb(elapsed_seconds, total_duration_seconds, dest_path.name, url),
                                            loop,
                                        )
                                    except Exception as pe:
                                        log.debug("HLS progress dispatch error: %s", pe)

                        packet.stream = streams_map[packet.stream.index]
                        output_container.mux(packet)

                    if progress_cb and total_duration_seconds > 0:
                        try:
                            asyncio.run_coroutine_threadsafe(
                                progress_cb(total_duration_seconds, total_duration_seconds, dest_path.name, url),
                                loop,
                            )
                        except Exception as pe:
                            log.debug("HLS final progress dispatch error: %s", pe)
        except Exception:
            if part_file.exists():
                try:
                    part_file.unlink(missing_ok=True)
                except Exception:
                    pass
            raise

    try:
        await asyncio.to_thread(_do_remux)
        if part_file.exists():
            part_file.replace(dest_path)
        log.info("HLS download completed successfully: %s", dest_path)
        return dest_path
    except asyncio.CancelledError:
        if part_file.exists():
            try:
                part_file.unlink(missing_ok=True)
            except Exception:
                pass
        raise
    except Exception as e:
        if part_file.exists():
            try:
                part_file.unlink(missing_ok=True)
            except Exception:
                pass
        if isinstance(e, DirectDownloadError):
            raise
        raise DirectDownloadError(f"HLS remuxing failed: {e}") from e
