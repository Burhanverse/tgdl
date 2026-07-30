from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional, Tuple

from ..config import settings

log = logging.getLogger(__name__)


def get_user_auth_dir(user_id: int | str) -> Path:
    """Returns directory path for user-specific auth credentials."""
    user_dir = settings.auth_dir / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


def get_user_mega_credentials(user_id: int | str) -> Tuple[Optional[str], Optional[str]]:
    """Returns (email, password) for user if saved in auth/{user_id}/mega.json."""
    creds_file = get_user_auth_dir(user_id) / "mega.json"
    if creds_file.exists():
        try:
            data = json.loads(creds_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                email = data.get("email")
                password = data.get("password")
                if email and password:
                    return str(email), str(password)
        except Exception as e:
            log.warning("Failed reading mega credentials for user %s: %s", user_id, e)
    return None, None


def save_user_mega_credentials(user_id: int | str, email: str, password: str) -> None:
    """Saves MEGA email and password for a user in auth/{user_id}/mega.json."""
    user_dir = get_user_auth_dir(user_id)
    creds_file = user_dir / "mega.json"
    data = {"email": email, "password": password}
    creds_file.write_text(json.dumps(data, indent=2), encoding="utf-8")


def delete_user_mega_credentials(user_id: int | str) -> bool:
    """Deletes saved MEGA credentials for a user. Returns True if deleted."""
    creds_file = get_user_auth_dir(user_id) / "mega.json"
    if creds_file.exists():
        try:
            creds_file.unlink()
            return True
        except Exception as e:
            log.warning("Failed deleting mega credentials for user %s: %s", user_id, e)
    return False
