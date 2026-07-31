from __future__ import annotations

import zipfile
from pathlib import Path
import pytest

from app.config import settings
from app.auth import is_authorized_user_or_chat, check_auth_on_startup
from app.handlers.gdlconf import validate_gdl_conf


def test_validate_gdl_conf_rejects_exec_and_python_postprocessors():
    """Verify validate_gdl_conf rejects configs with 'exec' or 'python' postprocessors."""
    exec_config = """
    {
        "extractor": {
            "postprocessors": [
                {
                    "name": "exec",
                    "command": "rm -rf /"
                }
            ]
        }
    }
    """
    ok, err, parsed = validate_gdl_conf(exec_config)
    assert ok is False
    assert "Forbidden postprocessor" in err or "exec" in err

    python_config = """
    {
        "extractor": {
            "postprocessors": [
                {
                    "name": "python",
                    "code": "import os; os.system('whoami')"
                }
            ]
        }
    }
    """
    ok, err, parsed = validate_gdl_conf(python_config)
    assert ok is False
    assert "Forbidden postprocessor" in err or "python" in err


def test_validate_gdl_conf_accepts_safe_postprocessors():
    """Verify validate_gdl_conf accepts known safe postprocessors."""
    safe_config = """
    {
        "extractor": {
            "postprocessors": [
                {
                    "name": "metadata"
                },
                {
                    "name": "mtime"
                }
            ]
        }
    }
    """
    ok, err, parsed = validate_gdl_conf(safe_config)
    assert ok is True
    assert parsed is not None


def test_authorization_filter_logic():
    """Verify is_authorized_user behaves correctly for restricted and unrestricted modes."""
    class DummyUser:
        def __init__(self, uid: int):
            self.id = uid

    class DummyUpdate:
        def __init__(self, uid: int):
            self.from_user = DummyUser(uid)

    # When list is empty (unrestricted mode), all requests are authorized
    settings.authorized_user_ids = []
    up1 = DummyUpdate(100)
    assert is_authorized_user_or_chat(up1) is True

    # When restricted, only configured user_ids pass
    settings.authorized_user_ids = [12345]

    authorized_up = DummyUpdate(12345)
    assert is_authorized_user_or_chat(authorized_up) is True

    unauthorized_up = DummyUpdate(99999)
    assert is_authorized_user_or_chat(unauthorized_up) is False

    # Reset
    settings.authorized_user_ids = []


def test_zip_slip_path_traversal_detection(tmp_path: Path):
    """Verify zipfile path traversal member check detects outside paths."""
    target_dir = tmp_path / "extracted"
    target_dir.mkdir()

    # Create member attempting traversal
    traversal_member = "../../etc/passwd"
    resolved_path = (target_dir.resolve() / traversal_member).resolve()
    assert resolved_path.is_relative_to(target_dir.resolve()) is False

    safe_member = "sub/file.txt"
    resolved_safe = (target_dir.resolve() / safe_member).resolve()
    assert resolved_safe.is_relative_to(target_dir.resolve()) is True
