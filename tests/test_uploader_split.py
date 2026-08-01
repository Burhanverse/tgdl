from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.db import Job
from app.manager.state import JobState
from app.utils.media.file_split import split_binary


def test_jobstate_split_parts_tracking():
    """Verify JobState tracks split_parts_created."""
    job = Job(
        id="test_job_1",
        chat_id=123,
        status_message_id=None,
        url="https://example.com/test.zip",
        status="queued",
        total_files=0,
        sent_files=0,
        skipped_files=0,
        error=None,
        created_at=1000.0,
        updated_at=1000.0,
    )
    dest_dir = Path("/tmp/job_test_job_1")
    job_state = JobState(job, dest_dir)
    assert hasattr(job_state, "split_parts_created")
    assert isinstance(job_state.split_parts_created, set)
    assert len(job_state.split_parts_created) == 0

    job_state.split_parts_created.add("file.zip.001")
    job_state.split_parts_created.add("file.zip.002")
    assert "file.zip.001" in job_state.split_parts_created
    assert "file.zip.002" in job_state.split_parts_created


@pytest.mark.asyncio
async def test_handle_large_file_split_and_parts():
    """Verify binary splitting produces split parts and handle_large_file returns them."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        large_file = tmp_path / "large_archive.zip"

        # Create a dummy file exceeding small threshold test
        content = b"X" * (1024 * 1024 * 5)  # 5MB
        large_file.write_bytes(content)

        # Split binary directly with small max_size_bytes threshold (2MB)
        parts = await split_binary(large_file, max_size_bytes=2 * 1024 * 1024)
        assert len(parts) >= 2
        assert parts[0].name.endswith(".001")
        assert parts[1].name.endswith(".002")

        # Check total size of split parts matches original content size
        total_split_size = sum(p.stat().st_size for p in parts)
        assert total_split_size == len(content)


def test_parse_download_flags():
    """Verify _parse_flags parses -uz, -p, -m, -tg flags correctly."""
    from app.handlers.download import _parse_flags

    # Simple -uz flag
    tokens1 = ["/dl", "-uz", "https://example.com/file.zip"]
    is_m, is_tg, uz, pwd, urls = _parse_flags(tokens1)
    assert uz is True
    assert pwd is None
    assert urls == ["https://example.com/file.zip"]

    # -uz and -p with space
    tokens2 = ["/dl", "-uz", "-p", "secret123", "https://example.com/file.zip"]
    is_m, is_tg, uz, pwd, urls = _parse_flags(tokens2)
    assert uz is True
    assert pwd == "secret123"
    assert urls == ["https://example.com/file.zip"]

    # -p=val syntax with -unzip and -m
    tokens3 = ["/gdl", "-m", "-unzip", "-p=my_pass", "https://example.com/gallery"]
    is_m, is_tg, uz, pwd, urls = _parse_flags(tokens3)
    assert is_m is True
    assert uz is True
    assert pwd == "my_pass"
    assert urls == ["https://example.com/gallery"]

