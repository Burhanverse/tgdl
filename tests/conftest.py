from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def setup_test_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Provide dummy Telegram credentials and isolated temp directories for unit testing."""
    monkeypatch.setenv("TG_API_ID", "12345")
    monkeypatch.setenv("TG_API_HASH", "0123456789abcdef0123456789abcdef")
    monkeypatch.setenv("TG_BOT_TOKEN", "123456789:ABCdefGHIjklMNOpqrsTUVwxyz")
    
    # Isolate data directory
    data_dir = tmp_path / "data"
    auth_dir = tmp_path / "auth"
    log_dir = tmp_path / "logs"
    data_dir.mkdir(parents=True, exist_ok=True)
    auth_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("AUTH_DIR", str(auth_dir))
    monkeypatch.setenv("LOG_DIR", str(log_dir))
