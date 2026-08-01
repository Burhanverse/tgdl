from pathlib import Path

import pytest

import app.uploader.telegram.core as tg_core
from app.db import JobStore
from app.utils.media import (
    is_photo_invalid_for_telegram_async,
    probe_audio_async,
)


def test_global_upload_semaphore_removed():
    """Verify global _upload_semaphore is no longer present in telegram core."""
    assert not hasattr(tg_core, "_upload_semaphore"), "_upload_semaphore should be removed to allow tg_max_concurrent_uploads"


@pytest.mark.asyncio
async def test_async_probe_and_photo_validation(tmp_path: Path):
    """Verify probe_audio_async and is_photo_invalid_for_telegram_async run asynchronously."""
    dummy_file = tmp_path / "test.png"
    dummy_file.write_bytes(b"\x00" * 100)

    # Calling async wrapper on non-image/dummy should return bool without blocking loop
    is_invalid = await is_photo_invalid_for_telegram_async(dummy_file)
    assert isinstance(is_invalid, bool)

    dummy_audio = tmp_path / "test.mp3"
    dummy_audio.write_bytes(b"\x00" * 100)
    meta = await probe_audio_async(dummy_audio)
    assert isinstance(meta, dict)
    assert "duration" in meta


@pytest.mark.asyncio
async def test_db_wal_mode_and_synchronous(tmp_path: Path):
    """Verify JobStore.open() configures PRAGMA journal_mode=WAL and PRAGMA synchronous=NORMAL."""
    db_file = tmp_path / "test_jobs.db"
    store = JobStore(db_file)
    await store.open()

    async with store.db.execute("PRAGMA journal_mode") as cursor:
        row = await cursor.fetchone()
        assert row[0].lower() == "wal"

    async with store.db.execute("PRAGMA synchronous") as cursor:
        row = await cursor.fetchone()
        # 1 corresponds to NORMAL in SQLite
        assert row[0] == 1

    await store.close()


def test_direct_url_json_parsing():
    """Verify is_direct_url correctly parses JSON array URLs now that json is imported."""
    from app.downloader.direct.core import is_direct_url
    json_url_payload = '["https://example.com/video.mp4", "https://example.com/image.png"]'
    assert is_direct_url(json_url_payload) is True
