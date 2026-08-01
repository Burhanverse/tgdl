from __future__ import annotations

from pathlib import Path
import pytest

from app.db import JobStore
from app.manager.core import queue_manager
from app.manager.state import JobState
from app.manager.status.status_utils import get_all_active_task_adapters


@pytest.mark.asyncio
async def test_get_all_active_task_adapters(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "test_status.sqlite3"
    test_store = JobStore(db_path)
    await test_store.open()

    job = await test_store.create_job(
        chat_id=12345,
        url="https://example.com/video.mp4",
    )
    job_state = JobState(job=job, dest_dir=tmp_path / "job_dir")

    monkeypatch.setattr("app.manager.core.store", test_store)
    monkeypatch.setitem(queue_manager.jobs, job.id, job_state)

    try:
        adapters = await get_all_active_task_adapters()
        assert len(adapters) >= 1
        matching_adapter = next((a for a in adapters if a.job.id == job.id), None)
        assert matching_adapter is not None
        assert matching_adapter.job_state == job_state
    finally:
        queue_manager.jobs.pop(job.id, None)
        await test_store.close()
