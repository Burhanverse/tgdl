from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.downloader.direct.core import DirectDownloader, DirectDownloadError, is_direct_url, is_m3u8_url
from app.downloader.direct.hls import (
    calculate_playlist_duration,
    download_hls,
    parse_master_playlist,
)


@pytest.mark.asyncio
async def test_is_direct_url_m3u8():
    assert is_direct_url("https://example.com/video.m3u8") is True
    assert is_direct_url("https://example.com/stream.m3u8?token=xyz#segment") is True


@pytest.mark.asyncio
async def test_is_m3u8_url_fast_path():
    assert await is_m3u8_url("https://example.com/video/playlist.m3u8") is True
    assert await is_m3u8_url("https://example.com/video/playlist.m3u8?auth=123") is True


@pytest.mark.asyncio
async def test_is_m3u8_url_content_sniffing():
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.headers = {"Content-Type": "application/vnd.apple.mpegurl"}
    mock_resp.content.read = AsyncMock(return_value=b"#EXTM3U\n#EXT-X-VERSION:3")

    mock_get = AsyncMock()
    mock_get.__aenter__.return_value = mock_resp

    mock_session = MagicMock()
    mock_session.get.return_value = mock_get

    res = await is_m3u8_url("https://example.com/stream/12345", session=mock_session)
    assert res is True


@pytest.mark.asyncio
async def test_is_m3u8_url_ssrf_blocked():
    with patch("app.downloader.direct.core.is_url_private_ip", return_value=True):
        res_no_ext = await is_m3u8_url("http://192.168.1.1/stream")
        assert res_no_ext is False


def test_parse_master_playlist():
    master_text = (
        "#EXTM3U\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360\n"
        "low/playlist.m3u8\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=2500000,RESOLUTION=1280x720\n"
        "high/playlist.m3u8\n"
    )
    base_url = "https://cdn.example.com/master.m3u8"
    variants = parse_master_playlist(master_text, base_url)
    assert len(variants) == 2
    assert variants[0] == (800000, "https://cdn.example.com/low/playlist.m3u8")
    assert variants[1] == (2500000, "https://cdn.example.com/high/playlist.m3u8")


def test_calculate_playlist_duration():
    media_text = (
        "#EXTM3U\n"
        "#EXTINF:10.000,\n"
        "seq1.ts\n"
        "#EXTINF:9.500,\n"
        "seq2.ts\n"
        "#EXTINF:5.250,\n"
        "seq3.ts\n"
        "#EXT-X-ENDLIST\n"
    )
    duration = calculate_playlist_duration(media_text)
    assert pytest.approx(duration, 0.001) == 24.75


@pytest.mark.asyncio
async def test_download_hls_live_stream_rejection(tmp_path: Path):
    media_text_live = (
        "#EXTM3U\n"
        "#EXT-X-VERSION:3\n"
        "#EXTINF:10.0,\n"
        "seq1.ts\n"
    )  # missing #EXT-X-ENDLIST

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.url = "https://example.com/live.m3u8"
    mock_resp.text = AsyncMock(return_value=media_text_live)

    mock_get = AsyncMock()
    mock_get.__aenter__.return_value = mock_resp

    with patch("aiohttp.ClientSession.get", return_value=mock_get):
        with pytest.raises(DirectDownloadError, match="Live HLS streams are not supported"):
            await download_hls("https://example.com/live.m3u8", tmp_path / "out.mp4")


@pytest.mark.asyncio
async def test_download_hls_success(tmp_path: Path):
    media_text_vod = (
        "#EXTM3U\n"
        "#EXT-X-TARGETDURATION:10\n"
        "#EXTINF:10.0,\n"
        "seq1.ts\n"
        "#EXT-X-ENDLIST\n"
    )

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.url = "https://example.com/vod.m3u8"
    mock_resp.text = AsyncMock(return_value=media_text_vod)

    mock_get = AsyncMock()
    mock_get.__aenter__.return_value = mock_resp

    # Mock PyAV container behavior
    mock_input = MagicMock()
    mock_input.__enter__.return_value = mock_input
    mock_output = MagicMock()
    mock_output.__enter__.return_value = mock_output

    mock_stream = MagicMock()
    mock_stream.type = "video"
    mock_stream.index = 0
    mock_stream.time_base = 1 / 90000

    mock_input.streams = [mock_stream]

    mock_packet = MagicMock()
    mock_packet.stream.index = 0
    mock_packet.pts = 900000  # 10s
    mock_packet.dts = 900000

    mock_input.demux.return_value = [mock_packet]

    out_file = tmp_path / "video.mp4"

    def mock_av_open(target, mode="r", options=None, format=None):
        if mode == "w":
            assert format == "mp4"
            # create empty output file simulating PyAV writing
            part_path = Path(target)
            part_path.write_bytes(b"mock mp4 content")
            return mock_output
        return mock_input

    progress_calls = []

    async def on_progress(current, total, filename, url):
        progress_calls.append((current, total, filename, url))

    with patch("aiohttp.ClientSession.get", return_value=mock_get):
        with patch("av.open", side_effect=mock_av_open):
            res_path = await download_hls(
                "https://example.com/vod.m3u8",
                out_file,
                progress_cb=on_progress,
            )
            assert res_path == out_file
            assert out_file.exists()
            assert out_file.read_bytes() == b"mock mp4 content"


@pytest.mark.asyncio
async def test_direct_downloader_delegates_m3u8(tmp_path: Path):
    downloader = DirectDownloader(dest_dir=tmp_path)

    with patch("app.downloader.direct.hls.download_hls", new_callable=AsyncMock) as mock_hls:
        mock_hls.return_value = tmp_path / "sample.mp4"

        with patch("aiohttp.ClientSession") as mock_sess_cls:
            mock_sess = AsyncMock()
            mock_sess_cls.return_value.__aenter__.return_value = mock_sess

            res = await downloader.download("https://example.com/sample.m3u8")
            assert len(res) == 1
            assert res[0] == tmp_path / "sample.mp4"
            mock_hls.assert_called_once()
            _, kwargs = mock_hls.call_args
            assert kwargs["dest_path"].name == "sample.mp4"
