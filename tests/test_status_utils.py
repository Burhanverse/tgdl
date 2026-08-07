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


@pytest.mark.asyncio
async def test_get_specific_tasks_user_filtering(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "test_status_filter.sqlite3"
    test_store = JobStore(db_path)
    await test_store.open()

    job_user1 = await test_store.create_job(chat_id=111, url="https://example.com/user1.mp4")
    job_user2 = await test_store.create_job(chat_id=222, url="https://example.com/user2.mp4")

    state1 = JobState(job=job_user1, dest_dir=tmp_path / "j1")
    state2 = JobState(job=job_user2, dest_dir=tmp_path / "j2")

    monkeypatch.setattr("app.manager.core.store", test_store)
    monkeypatch.setitem(queue_manager.jobs, job_user1.id, state1)
    monkeypatch.setitem(queue_manager.jobs, job_user2.id, state2)

    try:
        tasks_user1 = await status_utils.get_specific_tasks("All", user_id=111)
        assert len(tasks_user1) == 1
        assert tasks_user1[0].user_id == 111

        tasks_user2 = await status_utils.get_specific_tasks("All", user_id=222)
        assert len(tasks_user2) == 1
        assert tasks_user2[0].user_id == 222

        all_tasks = await status_utils.get_specific_tasks("All", user_id=None)
        assert len(all_tasks) == 2
    finally:
        queue_manager.jobs.pop(job_user1.id, None)
        queue_manager.jobs.pop(job_user2.id, None)
        await test_store.close()


@pytest.mark.asyncio
async def test_is_owner_check(monkeypatch):
    from app.auth import is_owner
    from app.config import settings

    # Case 1: owner_id set explicitly
    monkeypatch.setattr(settings, "owner_id", 999)
    monkeypatch.setattr(settings, "authorized_user_ids", [111, 222])

    assert is_owner(999) is True
    assert is_owner(111) is False
    assert is_owner(222) is False

    # Case 2: owner_id None, fallback to first authorized user
    monkeypatch.setattr(settings, "owner_id", None)
    assert is_owner(111) is True
    assert is_owner(222) is False
    assert is_owner(333) is False


@pytest.mark.asyncio
async def test_status_cmd_user_specific(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock
    from app.handlers.status import register_status_handlers
    from app.config import settings

    # Set owner to 999, non-owner authorized user to 12345
    monkeypatch.setattr(settings, "owner_id", 999)
    monkeypatch.setattr(settings, "authorized_user_ids", [999, 12345])

    handler_fn = None

    def mock_on_message(filters_arg):
        def decorator(fn):
            nonlocal handler_fn
            handler_fn = fn
            return fn
        return decorator

    mock_app = MagicMock()
    mock_app.on_message = mock_on_message
    mock_app.on_callback_query = lambda f: (lambda fn: fn)

    register_status_handlers(mock_app)
    assert handler_fn is not None

    sent_user_ids = []

    async def mock_send_status_message(message, user_id=0):
        sent_user_ids.append(user_id)

    async def mock_delete_message(message):
        pass

    monkeypatch.setattr("app.handlers.status.send_status_message", mock_send_status_message)
    monkeypatch.setattr("app.handlers.status.delete_message", mock_delete_message)

    # --- Non-Owner Tests (user_id = 12345) ---
    # Scenario 1: Non-owner /status defaults to sender user_id (12345)
    msg1 = AsyncMock()
    msg1.text = "/status"
    msg1.from_user.id = 12345
    msg1.chat.id = 99999
    await handler_fn(None, msg1)
    assert sent_user_ids[-1] == 12345

    # Scenario 2: Non-owner /status all is restricted to sender user_id (12345)
    msg2 = AsyncMock()
    msg2.text = "/status all"
    msg2.from_user.id = 12345
    msg2.chat.id = 99999
    await handler_fn(None, msg2)
    assert sent_user_ids[-1] == 12345

    # Scenario 3: Non-owner /status <other_id> is restricted to sender user_id (12345)
    msg3 = AsyncMock()
    msg3.text = "/status 888"
    msg3.from_user.id = 12345
    msg3.chat.id = 99999
    await handler_fn(None, msg3)
    assert sent_user_ids[-1] == 12345

    # --- Owner Tests (owner_id = 999) ---
    # Scenario 4: Owner /status defaults to 0 (all tasks)
    msg4 = AsyncMock()
    msg4.text = "/status"
    msg4.from_user.id = 999
    msg4.chat.id = 99999
    await handler_fn(None, msg4)
    assert sent_user_ids[-1] == 0

    # Scenario 5: Owner /status me uses owner's user_id (999)
    msg5 = AsyncMock()
    msg5.text = "/status me"
    msg5.from_user.id = 999
    msg5.chat.id = 99999
    await handler_fn(None, msg5)
    assert sent_user_ids[-1] == 999

    # Scenario 6: Owner /status <other_id> allows inspecting specific user's status
    msg6 = AsyncMock()
    msg6.text = "/status 12345"
    msg6.from_user.id = 999
    msg6.chat.id = 99999
    await handler_fn(None, msg6)
    assert sent_user_ids[-1] == 12345
