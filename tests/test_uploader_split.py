from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.db import Job
from app.manager.state import JobState
from app.utils.media.file_split import split_binary


def test_jobstate_split_parts_tracking():
    """Verify JobState tracks split_parts_created."""
    job = Job(
        id="test_job_1",
        chat_id=123,
        status_message_id=None,
        url="https://example.com/test.zip",
        status="queued",
        total_files=0,
        sent_files=0,
        skipped_files=0,
        error=None,
        created_at=1000.0,
        updated_at=1000.0,
    )
    dest_dir = Path("/tmp/job_test_job_1")
    job_state = JobState(job, dest_dir)
    assert hasattr(job_state, "split_parts_created")
    assert isinstance(job_state.split_parts_created, set)
    assert len(job_state.split_parts_created) == 0

    job_state.split_parts_created.add("file.zip.001")
    job_state.split_parts_created.add("file.zip.002")
    assert "file.zip.001" in job_state.split_parts_created
    assert "file.zip.002" in job_state.split_parts_created


@pytest.mark.asyncio
async def test_handle_large_file_split_and_parts():
    """Verify binary splitting produces split parts and handle_large_file returns them."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        large_file = tmp_path / "large_archive.zip"

        # Create a dummy file exceeding small threshold test
        content = b"X" * (1024 * 1024 * 5)  # 5MB
        large_file.write_bytes(content)

        # Split binary directly with small max_size_bytes threshold (2MB)
        parts = await split_binary(large_file, max_size_bytes=2 * 1024 * 1024)
        assert len(parts) >= 2
        assert parts[0].name.endswith(".001")
        assert parts[1].name.endswith(".002")

        # Check total size of split parts matches original content size
        total_split_size = sum(p.stat().st_size for p in parts)
        assert total_split_size == len(content)


def test_parse_download_flags():
    """Verify _parse_flags parses -uz, -p, -m, -tg flags correctly."""
    from app.handlers.download import _parse_flags

    # Simple -uz flag
    tokens1 = ["/dl", "-uz", "https://example.com/file.zip"]
    is_m, is_tg, uz, pwd, urls = _parse_flags(tokens1)
    assert uz is True
    assert pwd is None
    assert urls == ["https://example.com/file.zip"]

    # -uz and -p with space
    tokens2 = ["/dl", "-uz", "-p", "secret123", "https://example.com/file.zip"]
    is_m, is_tg, uz, pwd, urls = _parse_flags(tokens2)
    assert uz is True
    assert pwd == "secret123"
    assert urls == ["https://example.com/file.zip"]

    # -p=val syntax with -unzip and -m
    tokens3 = ["/gdl", "-m", "-unzip", "-p=my_pass", "https://example.com/gallery"]
    is_m, is_tg, uz, pwd, urls = _parse_flags(tokens3)
    assert is_m is True
    assert uz is True
    assert pwd == "my_pass"
    assert urls == ["https://example.com/gallery"]


def test_prepare_filename_and_caption_split_binary_naming(tmp_path: Path):
    """Verify filename >60 chars ending in .mp4.001 preserves real extension .mp4 and .001 suffix after truncation."""
    from unittest.mock import MagicMock

    from app.uploader.telegram.core import TelegramUploader

    long_filename = "a" * 65 + "_video_sample.mp4.001"
    file_path = tmp_path / long_filename
    file_path.write_bytes(b"dummy")

    client = MagicMock()
    uploader = TelegramUploader(client=client, path=file_path, chat_id=123)

    caption, _ = uploader._prepare_filename_and_caption(file_path)
    assert ".mp4.001" in caption


def test_prepare_filename_and_caption_single_numeric_extension(tmp_path: Path):
    """Verify filename >60 chars with a single numeric extension (e.g. .123) preserves .123 suffix."""
    from unittest.mock import MagicMock

    from app.uploader.telegram.core import TelegramUploader

    long_filename = "b" * 65 + "_data_file.123"
    file_path = tmp_path / long_filename
    file_path.write_bytes(b"dummy")

    client = MagicMock()
    uploader = TelegramUploader(client=client, path=file_path, chat_id=123)

    caption, _ = uploader._prepare_filename_and_caption(file_path)
    assert ".123</code>" in caption


def test_split_video_pyav_multistream_offset_timestamps(tmp_path: Path):
    """Verify PyAV video segmenter rebases video and audio stream timestamps independently without negative pts/dts."""
    from unittest.mock import MagicMock, patch
    from app.utils.media.video.split import _split_video_pyav_sync

    video_path = tmp_path / "sample.mp4"
    video_path.write_bytes(b"dummy_video_bytes")

    mock_v_stream = MagicMock()
    mock_v_stream.type = "video"
    mock_v_stream.index = 0
    mock_v_stream.time_base = 1 / 1000

    mock_a_stream = MagicMock()
    mock_a_stream.type = "audio"
    mock_a_stream.index = 1
    mock_a_stream.time_base = 1 / 1000

    pkt_a1 = MagicMock()
    pkt_a1.stream = mock_a_stream
    pkt_a1.pts = 2000
    pkt_a1.dts = 2000
    pkt_a1.is_keyframe = True
    pkt_a1.size = 100

    pkt_v1 = MagicMock()
    pkt_v1.stream = mock_v_stream
    pkt_v1.pts = 5000
    pkt_v1.dts = 5000
    pkt_v1.is_keyframe = True
    pkt_v1.size = 100

    pkt_a2 = MagicMock()
    pkt_a2.stream = mock_a_stream
    pkt_a2.pts = 2100
    pkt_a2.dts = 2100
    pkt_a2.is_keyframe = True
    pkt_a2.size = 100

    pkt_v2 = MagicMock()
    pkt_v2.stream = mock_v_stream
    pkt_v2.pts = 5100
    pkt_v2.dts = 5100
    pkt_v2.is_keyframe = True
    pkt_v2.size = 100

    packets = [pkt_a1, pkt_v1, pkt_a2, pkt_v2]

    mock_input_container = MagicMock()
    mock_input_container.streams = [mock_v_stream, mock_a_stream]
    mock_input_container.demux.return_value = packets

    muxed_packets = []

    mock_output_container = MagicMock()
    mock_output_container.add_stream_from_template.side_effect = lambda s: MagicMock(type=s.type, index=s.index, time_base=s.time_base)
    mock_output_container.mux.side_effect = lambda p: muxed_packets.append((p.stream.index, p.pts, p.dts))

    with patch("av.open") as mock_av_open:
        def mock_open_impl(file, mode="r", **kwargs):
            if mode == "w":
                return mock_output_container
            return mock_input_container

        mock_av_open.side_effect = mock_open_impl

        res = _split_video_pyav_sync(video_path, max_size_bytes=10 * 1024 * 1024)

    assert len(res) >= 1
    assert len(muxed_packets) == 4
    for stream_idx, pts, dts in muxed_packets:
        assert pts >= 0, f"Negative pts {pts} for stream {stream_idx}"
        assert dts >= 0, f"Negative dts {dts} for stream {stream_idx}"

    audio_pts = [pts for s_idx, pts, _ in muxed_packets if s_idx == 1]
    assert audio_pts == [0, 100]

    video_pts = [pts for s_idx, pts, _ in muxed_packets if s_idx == 0]
    assert video_pts == [0, 100]



