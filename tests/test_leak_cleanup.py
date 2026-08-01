from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from app.archive import _archive_ids
from app.conversion import _conversion_ids
from app.db import JobStore
from app.manager.core import QueueManager, _password_prompt_events
from app.manager.state import JobState
from app.manager.status.messaging import _last_edit_times
from app.pacing import TelegramRateLimiter


@pytest.mark.asyncio
async def test_cancel_job_full_cleanup(tmp_path: Path):
    db_path = tmp_path / "test_cancel_cleanup.sqlite3"
    store = JobStore(db_path)
    await store.open()

    qm = QueueManager()
    qm.store = store

    job = await store.create_job(chat_id=98765, url="https://example.com/file.zip")
    msg_id = 4455
    job_state = JobState(job=job, dest_dir=tmp_path / "cancel_job_dir")
    job_state.msg_id = msg_id

    qm.jobs[job.id] = job_state

    # Populate tracking dicts
    _archive_ids[job.id] = "archive_data"
    _conversion_ids[job.id] = "conversion_data"
    _password_prompt_events[job.id] = {}
    _last_edit_times[(job.chat_id, msg_id)] = time.time()

    assert job.id in qm.jobs
    assert job.id in _archive_ids
    assert job.id in _conversion_ids
    assert job.id in _password_prompt_events
    assert (job.chat_id, msg_id) in _last_edit_times

    cancelled = await qm.cancel_job(job.id)
    assert cancelled is True

    # Assert all references evicted
    assert job.id not in qm.jobs
    assert job.id not in _archive_ids
    assert job.id not in _conversion_ids
    assert job.id not in _password_prompt_events
    assert (job.chat_id, msg_id) not in _last_edit_times

    await store.close()


def test_pacing_stale_chat_cleanup():
    limiter = TelegramRateLimiter()

    stale_chat = 1111
    active_stale_chat = 2222
    recent_chat = 3333

    old_time = time.time() - 100000.0  # ~27.7 hours ago (> 24 hours)

    # Set up stale_chat
    limiter._chat_locks[stale_chat] = asyncio.Lock()
    limiter._chat_last_call[stale_chat] = old_time
    limiter._chat_last_upload[stale_chat] = old_time
    limiter._chat_floodwait_until[stale_chat] = old_time

    # Set up active_stale_chat (old timestamp, but active in queue_manager)
    limiter._chat_locks[active_stale_chat] = asyncio.Lock()
    limiter._chat_last_call[active_stale_chat] = old_time
    limiter._chat_last_upload[active_stale_chat] = old_time
    limiter._chat_floodwait_until[active_stale_chat] = old_time

    # Set up recent_chat
    limiter._chat_locks[recent_chat] = asyncio.Lock()
    limiter._chat_last_call[recent_chat] = time.time()

    evicted = limiter.cleanup_stale_chats(
        active_chat_ids={active_stale_chat},
        staleness_threshold=86400.0,
    )

    assert evicted == 1

    # stale_chat should be evicted from all dicts
    assert stale_chat not in limiter._chat_locks
    assert stale_chat not in limiter._chat_last_call
    assert stale_chat not in limiter._chat_last_upload
    assert stale_chat not in limiter._chat_floodwait_until

    # active_stale_chat should NOT be evicted because it's in active_chat_ids
    assert active_stale_chat in limiter._chat_locks
    assert active_stale_chat in limiter._chat_last_call

    # recent_chat should NOT be evicted because it's recent
    assert recent_chat in limiter._chat_locks
    assert recent_chat in limiter._chat_last_call
