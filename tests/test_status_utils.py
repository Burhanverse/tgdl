from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.db import JobStore
from app.manager.core import queue_manager
from app.manager.state import JobState
from app.manager.status import status_utils
from app.manager.status.status_utils import (
    get_all_active_task_adapters,
    get_system_stats_snapshot,
)


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


def test_get_system_stats_snapshot_caching(monkeypatch):
    current_clock = 1000.0
    cpu_call_count = 0

    def mock_time():
        return current_clock

    def mock_cpu_percent(interval=None):
        nonlocal cpu_call_count
        cpu_call_count += 1
        return 10.0 if cpu_call_count == 1 else 50.0

    monkeypatch.setattr(status_utils.time, "time", mock_time)
    monkeypatch.setattr(status_utils.psutil, "cpu_percent", mock_cpu_percent)

    # Reset module level cache
    monkeypatch.setattr(status_utils, "_system_stats_cache", None)
    monkeypatch.setattr(status_utils, "_system_stats_timestamp", 0.0)

    # First call - computes and caches (cpu_percent == 10.0)
    stats1 = get_system_stats_snapshot(max_age_seconds=2.0)
    assert stats1["cpu_percent"] == 10.0
    assert cpu_call_count == 1

    # Second call within max_age_seconds (clock advanced by 1s) - returns cached dict
    current_clock = 1001.0
    stats2 = get_system_stats_snapshot(max_age_seconds=2.0)
    assert stats2["cpu_percent"] == 10.0
    assert cpu_call_count == 1
    assert stats2 is stats1

    # Third call after max_age_seconds (clock advanced past 2s) - recomputes
    current_clock = 1003.0
    stats3 = get_system_stats_snapshot(max_age_seconds=2.0)
    assert stats3["cpu_percent"] == 50.0
    assert cpu_call_count == 2


def test_get_system_stats_snapshot_server_totals(monkeypatch):
    monkeypatch.setattr(status_utils, "SERVER_BOOT_TIME", 200.0)
    monkeypatch.setattr(status_utils.time, "time", lambda: 1200.0)

    mock_net = MagicMock()
    mock_net.bytes_sent = 1000000
    mock_net.bytes_recv = 5000000
    monkeypatch.setattr(status_utils.psutil, "net_io_counters", lambda: mock_net)

    # Reset module level cache
    monkeypatch.setattr(status_utils, "_system_stats_cache", None)
    monkeypatch.setattr(status_utils, "_system_stats_timestamp", 0.0)

    stats = get_system_stats_snapshot(max_age_seconds=2.0)
    assert stats["uptime_seconds"] == 1000.0
    assert stats["net_sent_bytes_since_start"] == 1000000
    assert stats["net_recv_bytes_since_start"] == 5000000
