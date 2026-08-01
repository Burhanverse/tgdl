from __future__ import annotations

import logging
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.bot import JsonFormatter, setup_logging
from app.config import Settings


def test_invalid_log_level_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    """(a) Verify invalid LOG_LEVEL raises ValidationError at config load time."""
    monkeypatch.setenv("LOG_LEVEL", "INVALID_LEVEL")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_setup_logging_debug_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """(b) Verify setup_logging() with log_level="DEBUG" sets pyrogram effective level to DEBUG."""
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    test_settings = Settings(_env_file=None, log_dir=tmp_path)
    monkeypatch.setattr("app.bot.settings", test_settings)

    root_logger = logging.getLogger()
    pyrogram_logger = logging.getLogger("pyrogram")

    try:
        setup_logging()
        assert root_logger.level == logging.DEBUG
        assert pyrogram_logger.level != logging.WARNING
        assert pyrogram_logger.getEffectiveLevel() == logging.DEBUG
    finally:
        root_logger.handlers.clear()


def test_setup_logging_warning_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """(c) Verify setup_logging() with log_level="WARNING" sets root & third-party loggers to WARNING."""
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    test_settings = Settings(_env_file=None, log_dir=tmp_path)
    monkeypatch.setattr("app.bot.settings", test_settings)

    root_logger = logging.getLogger()
    pyrogram_logger = logging.getLogger("pyrogram")
    aiosqlite_logger = logging.getLogger("aiosqlite")
    asyncio_logger = logging.getLogger("asyncio")
    httpx_logger = logging.getLogger("httpx")
    aiohttp_logger = logging.getLogger("aiohttp")

    try:
        setup_logging()
        assert root_logger.level == logging.WARNING
        assert pyrogram_logger.level == logging.WARNING
        assert aiosqlite_logger.level == logging.WARNING
        assert asyncio_logger.level == logging.WARNING
        assert httpx_logger.level == logging.WARNING
        assert aiohttp_logger.level == logging.WARNING
    finally:
        root_logger.handlers.clear()


def test_json_formatter_debug_extra_fields() -> None:
    """Verify JsonFormatter adds file, line, and func fields when is_debug=True."""
    formatter_debug = JsonFormatter(is_debug=True)
    record = logging.LogRecord(
        name="test_logger",
        level=logging.DEBUG,
        pathname="app/test_file.py",
        lineno=42,
        msg="Debug message test",
        args=(),
        exc_info=None,
        func="test_func",
    )
    formatted = formatter_debug.format(record)
    assert '"file": "test_file.py"' in formatted
    assert '"line": 42' in formatted
    assert '"func": "test_func"' in formatted
