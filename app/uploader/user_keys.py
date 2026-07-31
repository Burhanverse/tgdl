from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from ..config import settings

log = logging.getLogger(__name__)


def _get_user_keys_file(user_id: int | str) -> Path:
    user_dir = settings.auth_dir / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir / "keys.json"


def get_user_upload_keys(user_id: int | str) -> dict[str, str]:
    """Returns stored API keys dict for user: {'gofile': '...', 'pixeldrain': '...'}'."""
    keys_file = _get_user_keys_file(user_id)
    if keys_file.exists():
        try:
            content = keys_file.read_text(encoding="utf-8")
            data = json.loads(content)
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items() if v}
        except Exception as e:
            log.warning("Failed reading user keys from %s: %s", keys_file, e)
    return {}


def save_user_upload_key(user_id: int | str, service: str, key: str) -> None:
    """Saves user API key for service ('gofile' or 'pixeldrain') with 0o600 permissions."""
    keys_file = _get_user_keys_file(user_id)
    keys = get_user_upload_keys(user_id)
    keys[service.lower()] = key.strip()
    keys_file.write_text(json.dumps(keys, indent=2), encoding="utf-8")
    os.chmod(keys_file, 0o600)
    log.info("Saved user %s API key for %s to %s (permissions 0o600)", user_id, service, keys_file)


def delete_user_upload_key(user_id: int | str, service: str) -> None:
    """Deletes user API key for service."""
    keys_file = _get_user_keys_file(user_id)
    keys = get_user_upload_keys(user_id)
    if service.lower() in keys:
        keys.pop(service.lower())
        if keys:
            keys_file.write_text(json.dumps(keys, indent=2), encoding="utf-8")
            os.chmod(keys_file, 0o600)
        else:
            keys_file.unlink(missing_ok=True)


def resolve_upload_api_key(user_id: int | str | None, service: str) -> str | None:
    """Resolves API key for service ('gofile' or 'pixeldrain').
    
    1. Checks user's personal key if user_id is provided.
    2. If no personal key, checks settings.allow_shared_upload_keys. If True, returns owner global key.
    3. Otherwise, returns None (anonymous upload / no key).
    """
    service_clean = service.lower()

    if user_id:
        user_keys = get_user_upload_keys(user_id)
        user_key = user_keys.get(service_clean)
        if user_key:
            return user_key

    if settings.allow_shared_upload_keys:
        if service_clean == "gofile":
            return settings.gofile_api_key
        elif service_clean == "pixeldrain":
            return settings.pixeldrain_api_key

    return None
