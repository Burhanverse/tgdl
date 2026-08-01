from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db import JobStore
from app.handlers.callbacks import register_choice_callback_handlers
from app.handlers.conversion_state import conversion_session_store


@pytest.mark.asyncio
async def test_conversion_session_store_lifecycle():
    """Tests registration, event triggering, choice selection, and atomic pop in ConversionSessionStore."""
    job_id = "test_job_101"
    conv_id = "1"
    filename = "audio_sample.flac"

    conversion_session_store.register_conversion_id(job_id, conv_id, filename)
    assert conversion_session_store.get_conversion_filename(job_id, conv_id) == filename
    assert conversion_session_store.get_conversion_ids(job_id) == {"1": filename}
    assert conversion_session_store.get_next_conversion_id(job_id) == "2"

    evt = conversion_session_store.create_event(job_id, conv_id)
    assert not evt.is_set()

    conversion_session_store.set_choice(job_id, conv_id, "mp3")
    conversion_session_store.set_event(job_id, conv_id)

    assert evt.is_set()
    assert conversion_session_store.get_choice(job_id, conv_id) == "mp3"
    assert conversion_session_store.has_choice(job_id, conv_id) is True
    assert conversion_session_store.contains_job(job_id) is True

    conversion_session_store.add_converted_file(job_id, "audio_sample_converted.mp3")
    assert "audio_sample_converted.mp3" in conversion_session_store.get_converted_files(job_id)

    conversion_session_store.pop_job(job_id)
    assert conversion_session_store.contains_job(job_id) is False
    assert conversion_session_store.get_choice(job_id, conv_id) is None


@pytest.mark.asyncio
async def test_conversion_choice_callback_end_to_end(tmp_path: Path):
    """Simulates clicking a conversion-choice callback query button end-to-end."""
    db_path = tmp_path / "test_callback.sqlite3"
    store = JobStore(db_path)
    await store.open()

    chat_id = 123456
    job = await store.create_job(chat_id=chat_id, url="https://example.com/song.flac")
    job_id = job.id
    conv_id = "1"

    from app.handlers import callbacks
    callbacks.store = store

    # Pre-register conversion event and filename
    conversion_session_store.register_conversion_id(job_id, conv_id, "song.flac")
    evt = conversion_session_store.create_event(job_id, conv_id)

    mock_app = MagicMock()
    handler_fn = None

    def mock_on_callback_query(filters_arg):
        def decorator(fn):
            nonlocal handler_fn
            handler_fn = fn
            return fn
        return decorator

    mock_app.on_callback_query = mock_on_callback_query
    register_choice_callback_handlers(mock_app)

    # Find the conversion choice handler
    assert handler_fn is not None

    # Construct mock Pyrogram CallbackQuery
    mock_query = AsyncMock()
    mock_query.data = f"convert_mp3:{job_id}:{conv_id}"

    mock_match = MagicMock()
    mock_match.group = lambda i: {"1": "mp3", "2": job_id, "3": conv_id}[str(i)]
    mock_query.matches = [mock_match]

    mock_message = AsyncMock()
    mock_message.chat.id = chat_id
    mock_query.message = mock_message
    mock_query.from_user.id = chat_id

    # Execute conversion choice handler
    await handler_fn(mock_app, mock_query)

    # Assert choice set in store & event triggered
    assert conversion_session_store.get_choice(job_id, conv_id) == "mp3"
    assert evt.is_set() is True
    mock_query.answer.assert_called_once()
    mock_message.edit_text.assert_called_once()

    await store.close()
