from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.uploader.telegram.core import TelegramUploader
from app.uploader.video.processor import (
    _probe_video_sync,
    _take_screenshots_sync,
    probe_video,
    take_screenshots,
)


def test_take_screenshots_aborts_after_three_consecutive_failures(tmp_path: Path):
    video_path = tmp_path / "corrupt_video.mp4"
    video_path.write_bytes(b"\x00" * 1024)

    mock_container = MagicMock()
    mock_stream = MagicMock()
    mock_stream.type = "video"
    mock_stream.time_base = 1 / 1000
    mock_container.streams = [mock_stream]
    # container.decode throws an exception for every attempt
    mock_container.decode.side_effect = Exception("Corrupt frame decode error")

    with (
        patch("av.open", return_value=mock_container) as mock_av_open,
        patch("logging.Logger.warning") as mock_log_warning,
    ):
        mock_container.__enter__.return_value = mock_container
        shots = _take_screenshots_sync(video_path, duration=300)

        assert shots == []
        # Should abort after 3 consecutive failures (3 av.open calls instead of 9)
        assert mock_av_open.call_count == 3
        # Ensure abort summary warning was logged
        summary_logged = any(
            "Aborting screenshot capture" in str(call_args)
            for call_args in mock_log_warning.call_args_list
        )
        assert summary_logged


def test_take_screenshots_keeps_partial_success_before_abort(tmp_path: Path):
    video_path = tmp_path / "partially_corrupt_video.mp4"
    video_path.write_bytes(b"\x00" * 1024)

    mock_stream = MagicMock()
    mock_stream.type = "video"
    mock_stream.time_base = 1 / 1000

    mock_frame = MagicMock()
    mock_image = MagicMock()
    mock_frame.to_image.return_value = mock_image

    call_counter = 0

    def mock_open_impl(*args, **kwargs):
        nonlocal call_counter
        call_counter += 1
        c = MagicMock()
        c.__enter__.return_value = c
        c.streams = [mock_stream]

        if call_counter in (1, 2):
            # First 2 attempts succeed
            c.decode.return_value = [mock_frame]
        else:
            # Attempts 3, 4, 5 fail
            c.decode.side_effect = Exception("Decode failed after offset")
        return c

    with (
        patch("av.open", side_effect=mock_open_impl),
        patch("logging.Logger.warning") as mock_log_warning,
    ):
        shots = _take_screenshots_sync(video_path, duration=300)

        # 2 succeeded, 3 failed -> aborts on attempt 5 (total 5 av.open calls)
        assert len(shots) == 2
        assert call_counter == 5
        summary_logged = any(
            "Aborting screenshot capture" in str(call_args)
            for call_args in mock_log_warning.call_args_list
        )
        assert summary_logged


def test_probe_video_decodable_false_on_invalid_file(tmp_path: Path):
    video_path = tmp_path / "bad.mp4"
    video_path.write_bytes(b"invalid header")

    res = _probe_video_sync(video_path)
    assert res.get("decodable") is False


@pytest.mark.asyncio
async def test_upload_file_short_circuits_undecodable_video(tmp_path: Path):
    video_path = tmp_path / "undecodable.mp4"
    video_path.write_bytes(b"dummy")

    client = MagicMock()
    client.send_video = AsyncMock()

    uploader = TelegramUploader(client=client, chat_id=123, path=video_path)

    with (
        patch("app.uploader.telegram.core.probe_video", new_callable=AsyncMock) as mock_probe,
        patch("app.uploader.telegram.core.extract_video_thumbnail", new_callable=AsyncMock) as mock_thumb,
        patch("app.uploader.telegram.core.take_screenshots", new_callable=AsyncMock) as mock_shots,
        patch("app.uploader.telegram.core.telegram_limiter.acquire_upload", new_callable=AsyncMock),
    ):
        mock_probe.return_value = {"duration": 200, "width": 1280, "height": 720, "decodable": False}

        await uploader._upload_file(cap_mono="caption", file_path=video_path)

        mock_probe.assert_called_once_with(video_path)
        # thumbnail and screenshots should be skipped completely
        mock_thumb.assert_not_called()
        mock_shots.assert_not_called()
        client.send_video.assert_called_once()


@pytest.mark.asyncio
async def test_upload_file_short_circuits_screenshots_when_thumbnail_fails(tmp_path: Path):
    video_path = tmp_path / "thumb_fails.mp4"
    video_path.write_bytes(b"dummy")

    client = MagicMock()
    client.send_video = AsyncMock()

    uploader = TelegramUploader(client=client, chat_id=123, path=video_path)

    with (
        patch("app.uploader.telegram.core.probe_video", new_callable=AsyncMock) as mock_probe,
        patch("app.uploader.telegram.core.extract_video_thumbnail", new_callable=AsyncMock) as mock_thumb,
        patch("app.uploader.telegram.core.take_screenshots", new_callable=AsyncMock) as mock_shots,
        patch("app.uploader.telegram.core.telegram_limiter.acquire_upload", new_callable=AsyncMock),
    ):
        mock_probe.return_value = {"duration": 200, "width": 1280, "height": 720, "decodable": True}
        mock_thumb.return_value = None  # Thumbnail extraction failed

        await uploader._upload_file(cap_mono="caption", file_path=video_path)

        mock_probe.assert_called_once_with(video_path)
        mock_thumb.assert_called_once_with(video_path)
        # screenshots should be skipped because thumb_path is None
        mock_shots.assert_not_called()
        client.send_video.assert_called_once()
