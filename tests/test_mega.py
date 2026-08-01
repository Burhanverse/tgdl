from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.handlers.download import _parse_flags
from app.mega import MegaClient, MegaDownloader, is_mega_url


def test_is_mega_url():
    """Verify is_mega_url identifies MEGA URLs correctly."""
    assert is_mega_url("https://mega.nz/file/ABC#123") is True
    assert is_mega_url("https://mega.nz/folder/XYZ#456") is True
    assert is_mega_url("https://mega.co.nz/#!ABC!123") is True
    assert is_mega_url("https://mega.io/file/ABC#123") is True
    assert is_mega_url("mega:https://mega.nz/file/ABC#123") is True
    assert is_mega_url("https://example.com/file.zip") is False
    assert is_mega_url("") is False


def test_mega_client_parse_url():
    """Verify MegaClient parses MEGA URLs correctly."""
    client = MegaClient()
    info = client.parse_url("https://mega.nz/file/samplehandle#samplekey")
    assert info.is_folder is False
    assert info.public_handle == "samplehandle"
    assert info.public_key == "samplekey"

    folder_info = client.parse_url("mega:https://mega.nz/folder/folderhandle#folderkey")
    assert folder_info.is_folder is True
    assert folder_info.public_handle == "folderhandle"
    assert folder_info.public_key == "folderkey"


@pytest.mark.asyncio
async def test_mega_client_login():
    """Verify MegaClient calls login on MegaNzClient."""
    mock_raw_client = MagicMock()
    mock_raw_client.logged_in = False
    mock_raw_client.login = AsyncMock()

    client = MegaClient()
    client._client = mock_raw_client

    await client.ensure_logged_in()
    mock_raw_client.login.assert_awaited_once_with()



def test_parse_mega_flags():
    """Verify _parse_flags parses /mega flags (-m, -tg, -uz, -p, urls)."""
    tokens = ["/mega", "-m", "-tg", "-uz", "-p", "secret123", "https://mega.nz/file/ABC#123"]
    is_m, is_tg, uz, pwd, urls = _parse_flags(tokens)
    assert is_m is True
    assert is_tg is True
    assert uz is True
    assert pwd == "secret123"
    assert urls == ["https://mega.nz/file/ABC#123"]


@pytest.mark.asyncio
async def test_mega_downloader_progress_callback():
    """Verify MegaDownloader invokes progress_callback when progress hooks trigger."""
    progress_updates = []

    def on_progress(downloaded: int, speed: float, filename: str):
        progress_updates.append((downloaded, speed, filename))

    mock_client = MagicMock(spec=MegaClient)
    mock_client.download_url = AsyncMock()

    downloader = MegaDownloader(client=mock_client, progress_callback=on_progress)

    with tempfile.TemporaryDirectory() as tmpdir:
        dest = Path(tmpdir)

        # Test progress hook factory directly
        factory = downloader._create_hook_factory()
        with factory("test_file.bin", 1000, "DOWN") as hook:
            hook(500)
            hook(500)

        assert len(progress_updates) == 2
        assert progress_updates[0][0] == 500
        assert progress_updates[0][2] == "test_file.bin"
        assert progress_updates[1][0] == 1000

        # Test download_link dispatch
        await downloader.download_link("https://mega.nz/file/ABC#123", dest)
        mock_client.download_url.assert_awaited_once_with("https://mega.nz/file/ABC#123", output_dir=dest)


def test_user_mega_credentials_save_get_delete():
    """Verify saving, retrieving, and deleting per-user MEGA credentials."""
    from app.mega import (
        delete_user_mega_credentials,
        get_user_mega_credentials,
        save_user_mega_credentials,
    )

    user_id = 999888
    delete_user_mega_credentials(user_id)

    email, pwd = get_user_mega_credentials(user_id)
    assert email is None
    assert pwd is None

    save_user_mega_credentials(user_id, "user99@mega.test", "SecretPass123")
    email, pwd = get_user_mega_credentials(user_id)
    assert email == "user99@mega.test"
    assert pwd == "SecretPass123"

    deleted = delete_user_mega_credentials(user_id)
    assert deleted is True
    email, pwd = get_user_mega_credentials(user_id)
    assert email is None
    assert pwd is None

