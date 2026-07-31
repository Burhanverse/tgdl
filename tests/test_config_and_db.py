from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.db import JobStatus, JobStore


@pytest.mark.asyncio
async def test_settings_validation(monkeypatch, tmp_path):
    monkeypatch.setenv("TG_API_ID", "99999")
    monkeypatch.setenv("TG_API_HASH", "test_hash")
    monkeypatch.setenv("TG_BOT_TOKEN", "123:test_token")
    monkeypatch.setenv("LOG_FORMAT", "json")
    
    settings = Settings()
    assert settings.tg_api_id == 99999
    assert settings.tg_api_hash == "test_hash"
    assert settings.log_format == "json"
    settings.validate_credentials()  # should not raise


@pytest.mark.asyncio
async def test_settings_missing_credentials():
    settings = Settings(tg_api_id=0, tg_api_hash="", tg_bot_token="")
    with pytest.raises(ValueError, match="Missing required environment variables"):
        settings.validate_credentials()


@pytest.mark.asyncio
async def test_job_store(tmp_path: Path):
    db_path = tmp_path / "test_state.sqlite3"
    store = JobStore(db_path)
    await store.open()

    job = await store.create_job(
        chat_id=12345,
        url="https://example.com/test.zip",
        split_large_files=1,
    )
    assert job.id is not None
    assert job.status == JobStatus.QUEUED

    fetched = await store.get_job(job.id)
    assert fetched is not None
    assert fetched.url == "https://example.com/test.zip"

    await store.update_progress(job.id, status=JobStatus.DOWNLOADING)
    updated = await store.get_job(job.id)
    assert updated.status == JobStatus.DOWNLOADING

    await store.close()
