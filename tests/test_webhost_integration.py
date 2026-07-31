from pathlib import Path
from unittest.mock import patch

import pytest

from app.uploader.pixeldrain import upload_to_pixeldrain
from app.uploader.gofile import upload_to_gofile, GoFileUploader
from app.uploader.fileditch import upload_to_fileditch, FileDitchUploader


@pytest.mark.asyncio
async def test_upload_to_pixeldrain_success(tmp_path: Path):
    test_file = tmp_path / "test.txt"
    test_file.write_text("hello pixeldrain")

    progress_calls = []

    async def progress_cb(current, total):
        progress_calls.append((current, total))

    mock_resp = {"id": "abc12345", "success": True}

    def mock_upload_file(file_path, api_key=None, anonymous=True, progress_callback=None):
        if progress_callback:
            progress_callback(10, 100)
            progress_callback(100, 100)
        return mock_resp

    with patch("webhost.pixeldrain.upload_file", side_effect=mock_upload_file):
        res, logs = await upload_to_pixeldrain(test_file, progress_callback=progress_cb)

    assert res.get("id") == "abc12345"
    assert "Uploaded Successfully" in logs
    assert len(progress_calls) == 2
    assert progress_calls[-1] == (100, 100)


@pytest.mark.asyncio
async def test_upload_to_pixeldrain_file_not_found(tmp_path: Path):
    non_existent = tmp_path / "missing.txt"
    res, logs = await upload_to_pixeldrain(non_existent)
    assert res.get("error") == "File not found"
    assert any("File not found" in log for log in logs)


@pytest.mark.asyncio
async def test_upload_to_gofile_success(tmp_path: Path):
    test_file = tmp_path / "test_gf.txt"
    test_file.write_text("hello gofile")

    mock_resp = {
        "status": "ok",
        "data": {
            "downloadPage": "https://gofile.io/d/xyz789"
        }
    }

    with patch("webhost.gofile.upload_file", return_value=mock_resp):
        res, logs = await upload_to_gofile(test_file)

    assert res.get("status") == "ok"
    assert res["data"]["downloadPage"] == "https://gofile.io/d/xyz789"
    assert any("Uploaded to GoFile successfully" in log for log in logs)


@pytest.mark.asyncio
async def test_gofile_uploader_class(tmp_path: Path):
    test_file = tmp_path / "test_gf2.txt"
    test_file.write_text("hello gofile uploader class")

    mock_resp = {
        "status": "ok",
        "data": {
            "downloadPage": "https://gofile.io/d/xyz123"
        }
    }

    with patch("webhost.gofile.upload_file", return_value=mock_resp):
        uploader = GoFileUploader(test_file)
        links, summary = await uploader.upload()

    assert links == ["https://gofile.io/d/xyz123"]
    assert summary["uploaded"] == 1
    assert summary["failed"] == 0


@pytest.mark.asyncio
async def test_upload_to_fileditch_success(tmp_path: Path):
    test_file = tmp_path / "test_fd.txt"
    test_file.write_text("hello fileditch")

    mock_resp = {
        "success": True,
        "url": "https://fileditchfiles.st/test_fd.txt"
    }

    with patch("webhost.fileditch.upload_file", return_value=mock_resp):
        res, logs = await upload_to_fileditch(test_file)

    assert res.get("success") is True
    assert res.get("url") == "https://fileditchfiles.st/test_fd.txt"
    assert any("Uploaded to FileDitch successfully" in log for log in logs)


@pytest.mark.asyncio
async def test_fileditch_uploader_class(tmp_path: Path):
    test_file = tmp_path / "test_fd2.txt"
    test_file.write_text("hello fileditch class")

    mock_resp = {
        "success": True,
        "url": "https://fileditchfiles.st/test_fd2.txt"
    }

    with patch("webhost.fileditch.upload_file", return_value=mock_resp):
        uploader = FileDitchUploader(test_file)
        urls, summary = await uploader.upload()

    assert urls == ["https://fileditchfiles.st/test_fd2.txt"]
    assert summary["uploaded"] == 1
    assert summary["failed"] == 0
