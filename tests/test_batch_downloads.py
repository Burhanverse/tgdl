from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.downloader.direct.core import DirectDownloader, DirectDownloadError
from app.gdrive.downloader import GoogleDriveDownloader
from app.manager.core import JobState, QueueManager
from app.mega import MegaDownloader
from app.db import Job, JobStatus


@pytest.mark.asyncio
async def test_direct_downloader_batch_strips_direct_prefix(tmp_path: Path):
    """Verify DirectDownloader.download() strips 'direct:' prefix from JSON array URLs."""
    downloader = DirectDownloader(dest_dir=tmp_path)
    urls = [
        "direct:https://example.com/file1.mp4",
        "direct:https://example.com/file2.mp4",
        "direct:https://example.com/file3.mp4",
    ]
    json_urls = json.dumps(urls)

    mock_item_download = AsyncMock()
    mock_item_download.side_effect = lambda session, url, filename, subpath: tmp_path / Path(url).name

    with patch.object(downloader, "_download_content_item", side_effect=mock_item_download):
        with patch("aiohttp.ClientSession"):
            res = await downloader.download(json_urls)
            assert len(res) == 3
            assert mock_item_download.call_count == 3
            called_urls = [call.kwargs["url"] for call in mock_item_download.call_args_list]
            assert called_urls == [
                "https://example.com/file1.mp4",
                "https://example.com/file2.mp4",
                "https://example.com/file3.mp4",
            ]


@pytest.mark.asyncio
async def test_direct_downloader_partial_failure_succeeds(tmp_path: Path):
    """Verify DirectDownloader only fails if all items in batch fail."""
    downloader = DirectDownloader(dest_dir=tmp_path)
    urls = [
        "https://example.com/file1.mp4",
        "https://example.com/file2.mp4",
        "https://example.com/file3.mp4",
    ]
    json_urls = json.dumps(urls)

    async def mock_download_item(session, url, filename, subpath):
        if "file2" in url:
            raise ValueError("HTTP 500 Connection Refused")
        f = tmp_path / Path(url).name
        f.touch()
        return f

    with patch.object(downloader, "_download_content_item", side_effect=mock_download_item):
        with patch("aiohttp.ClientSession"):
            res = await downloader.download(json_urls)
            assert len(res) == 2
            assert (tmp_path / "file1.mp4") in res
            assert (tmp_path / "file3.mp4") in res


@pytest.mark.asyncio
async def test_direct_downloader_all_failure_raises(tmp_path: Path):
    """Verify DirectDownloader raises DirectDownloadError when all items fail."""
    downloader = DirectDownloader(dest_dir=tmp_path)
    urls = ["https://example.com/file1.mp4", "https://example.com/file2.mp4"]
    json_urls = json.dumps(urls)

    with patch.object(downloader, "_download_content_item", side_effect=ValueError("Download failed")):
        with patch("aiohttp.ClientSession"):
            with pytest.raises(DirectDownloadError, match="All 2 direct file downloads failed"):
                await downloader.download(json_urls)


@pytest.mark.asyncio
async def test_mega_downloader_batch_partial_failure(tmp_path: Path):
    """Verify MegaDownloader processes all URLs and only fails if ALL fail."""
    mock_client = MagicMock()
    mock_client.ensure_logged_in = AsyncMock()

    async def mock_download_url(url, output_dir):
        if "fail" in url:
            raise RuntimeError("MEGA download error")
        (output_dir / f"{Path(url).name}.bin").touch()

    mock_client.download_url = AsyncMock(side_effect=mock_download_url)
    downloader = MegaDownloader(client=mock_client)

    urls = [
        "mega:https://mega.nz/file/ABC1",
        "mega:https://mega.nz/file/fail2",
        "mega:https://mega.nz/file/ABC3",
    ]
    res = await downloader.download_link(json.dumps(urls), tmp_path)
    assert len(res) == 2
    assert mock_client.download_url.call_count == 3


@pytest.mark.asyncio
async def test_manager_passes_job_url_to_downloaders(tmp_path: Path):
    """Verify Manager _process_download passes full job.url to Mega & Direct downloaders."""
    mock_store = AsyncMock()
    manager = QueueManager()
    manager.client = MagicMock()
    manager.store = mock_store

    urls = [
        "direct:https://example.com/a.mp4",
        "direct:https://example.com/b.mp4",
        "direct:https://example.com/c.mp4",
    ]
    job_url_json = json.dumps(urls)

    job = Job(
        id="job123",
        chat_id=100,
        status_message_id=None,
        url=job_url_json,
        status=JobStatus.QUEUED,
        total_files=0,
        sent_files=0,
        skipped_files=0,
        error=None,
        created_at=0,
        updated_at=0,
    )
    job_state = JobState(job=job, dest_dir=tmp_path)
    mock_store.get_job.return_value = job

    with patch("app.downloader.download_direct", new_callable=AsyncMock) as mock_direct:
        mock_direct.return_value = [tmp_path / "a.mp4", tmp_path / "b.mp4", tmp_path / "c.mp4"]
        with patch("app.manager.core.safe_delete", new_callable=AsyncMock):
            await manager._process_download(job_state)
            mock_direct.assert_called_once()
            called_target_url = mock_direct.call_args[0][0]
            assert called_target_url == job_url_json


@pytest.mark.asyncio
async def test_manager_passes_mega_job_url(tmp_path: Path):
    """Verify Manager _process_download passes unreduced job.url to MegaDownloader."""
    mock_store = AsyncMock()
    manager = QueueManager()
    manager.client = MagicMock()
    manager.store = mock_store

    urls = [
        "mega:https://mega.nz/file/ABC1",
        "mega:https://mega.nz/file/ABC2",
    ]
    job_url_json = json.dumps(urls)

    job = Job(
        id="job456",
        chat_id=100,
        status_message_id=None,
        url=job_url_json,
        status=JobStatus.QUEUED,
        total_files=0,
        sent_files=0,
        skipped_files=0,
        error=None,
        created_at=0,
        updated_at=0,
    )
    job_state = JobState(job=job, dest_dir=tmp_path)
    mock_store.get_job.return_value = job

    with patch("app.mega.MegaDownloader.download_link", new_callable=AsyncMock) as mock_mega_dl:
        mock_mega_dl.return_value = [tmp_path / "ABC1.bin", tmp_path / "ABC2.bin"]
        with patch("app.manager.core.safe_delete", new_callable=AsyncMock):
            await manager._process_download(job_state)
            mock_mega_dl.assert_called_once()
            called_url = mock_mega_dl.call_args[0][0]
            assert called_url == job_url_json
