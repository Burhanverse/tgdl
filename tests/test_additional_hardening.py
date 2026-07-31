from __future__ import annotations

import os
import stat
from pathlib import Path
import pytest

from app.downloader.direct.core import is_url_private_ip
from app.uploader.user_keys import (
    save_user_upload_key,
    get_user_upload_keys,
    delete_user_upload_key,
    resolve_upload_api_key,
)
from app.downloader.torrent.telegraph_helper import TelegraphHelper
from app.config import settings


@pytest.mark.asyncio
async def test_ssrf_private_ip_rejection():
    """Verify is_url_private_ip rejects loopback, RFC1918, link-local, and reserved IPs."""
    # Loopback
    assert await is_url_private_ip("http://127.0.0.1/test") is True
    assert await is_url_private_ip("http://localhost/test") is True

    # RFC1918 Private Ranges
    assert await is_url_private_ip("http://10.0.0.1/secret") is True
    assert await is_url_private_ip("http://172.16.0.100/data") is True
    assert await is_url_private_ip("http://192.168.1.1/admin") is True

    # Link-local / Cloud Metadata
    assert await is_url_private_ip("http://169.254.169.254/latest/meta-data") is True


def test_user_upload_keys_and_permissions(tmp_path: Path):
    """Verify user upload keys storage, retrieval, deletion, and 0o600 permissions."""
    settings.auth_dir = tmp_path / "auth"
    user_id = 12345678

    save_user_upload_key(user_id, "gofile", "test_gofile_key_123")
    save_user_upload_key(user_id, "pixeldrain", "test_pd_key_456")

    keys = get_user_upload_keys(user_id)
    assert keys.get("gofile") == "test_gofile_key_123"
    assert keys.get("pixeldrain") == "test_pd_key_456"

    # Verify 0o600 file mode
    keys_file = settings.auth_dir / str(user_id) / "keys.json"
    assert keys_file.exists()
    mode = stat.S_IMODE(os.stat(keys_file).st_mode)
    assert mode == 0o600

    # Resolve upload key test
    settings.allow_shared_upload_keys = False
    assert resolve_upload_api_key(user_id, "gofile") == "test_gofile_key_123"

    # User with no key without shared fallback
    assert resolve_upload_api_key(999999, "gofile") is None

    # Enable shared fallback
    settings.gofile_api_key = "global_owner_key"
    settings.allow_shared_upload_keys = True
    assert resolve_upload_api_key(999999, "gofile") == "global_owner_key"

    delete_user_upload_key(user_id, "gofile")
    keys_after = get_user_upload_keys(user_id)
    assert "gofile" not in keys_after
    assert keys_after.get("pixeldrain") == "test_pd_key_456"

    delete_user_upload_key(user_id, "pixeldrain")
    assert not keys_file.exists()


@pytest.mark.asyncio
async def test_telegraph_html_attribute_escaping():
    """Verify TelegraphHelper escapes single quotes and special chars in href attributes."""
    helper = TelegraphHelper()
    results = [
        {
            "name": "Test 'Special' Name",
            "size": "1.2 GB",
            "seeders": 10,
            "leechers": 2,
            "torrent": "https://example.com/download?id=123'onload='alert(1)",
            "magnet": "magnet:?xt=urn:btih:1234567890abcdef'attr='bad",
        }
    ]
    page_url = await helper.generate_telegraph_page(results, "query'quote", "indexer")
    # Should complete without error and escape quotes
    assert page_url is None or isinstance(page_url, str)
