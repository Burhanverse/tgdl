from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import settings
from app.downloader.aria2c.torrent.core import DownloadResult, download_via_aria2_async
from app.handlers.download import _parse_aria_flags, register_download_handlers


def _get_aria_cmd_handler() -> callable:
    handlers = []
    mock_app = MagicMock()

    def mock_on_message(filter_obj):
        def decorator(fn):
            if hasattr(fn, "__name__") and fn.__name__ == "aria_cmd":
                handlers.append(fn)
            return fn
        return decorator

    mock_app.on_message = mock_on_message
    register_download_handlers(mock_app)
    return handlers[0]


@pytest.mark.asyncio
async def test_download_via_aria2_async_http_target(tmp_path: Path):
    """Verify download_via_aria2_async works for a non-bittorrent HTTP target without tracker injection."""
    with patch("app.downloader.aria2c.torrent.core.start_aria2_daemon", new_callable=AsyncMock), \
         patch("app.downloader.aria2c.torrent.core.ARIA2_PROC", MagicMock(returncode=None)), \
         patch("app.downloader.aria2c.torrent.core.ARIA2_PORT", 6800), \
         patch("app.downloader.aria2c.torrent.core.async_rpc_call", new_callable=AsyncMock) as mock_rpc:

        def rpc_side_effect(port, method, params):
            if method == "aria2.addUri":
                return {"result": "gid123"}
            elif method == "aria2.tellStatus":
                return {"result": {"status": "complete", "completedLength": "100", "totalLength": "100"}}
            elif method == "aria2.removeDownloadResult":
                return {"result": "OK"}
            return {}

        mock_rpc.side_effect = rpc_side_effect

        # Create a dummy file in tmp_path to simulate completed download output
        test_file = tmp_path / "test.zip"
        test_file.write_bytes(b"dummy content")

        res = await download_via_aria2_async(
            "http://example.com/test.zip",
            tmp_path,
            options={"max-connection-per-server": "8"}
        )

        assert res.ok is True
        assert test_file in res.files

        # Verify addUri call parameters
        add_uri_calls = [c for c in mock_rpc.call_args_list if c.args[1] == "aria2.addUri"]
        assert len(add_uri_calls) == 1
        params = add_uri_calls[0].args[2]
        assert params[0] == ["http://example.com/test.zip"]
        options = params[1]
        assert options["dir"] == str(tmp_path)
        assert options["max-connection-per-server"] == "8"
        assert "bt-tracker" not in options


def test_parse_aria_flags_curated_mapping():
    """Verify _parse_aria_flags maps curated flags to aria2 RPC option names."""
    tokens = [
        "/aria",
        "-c", "8",
        "-s", "4",
        "--min-split-size", "10M",
        "--max-tries", "3",
        "--retry-wait", "5",
        "--ua", "CustomUA/1.0",
        "--referer", "http://referer.example.com",
        "--proxy", "http://proxy.example.com:8080",
        "--checksum", "sha-256=abcdef123456",
        "--out", "custom_name.zip",
        "--speed", "5M",
        "http://example.com/file.zip"
    ]

    opts = _parse_aria_flags(tokens)

    assert opts["max-connection-per-server"] == "8"
    assert opts["split"] == "4"
    assert opts["min-split-size"] == "10M"
    assert opts["max-tries"] == "3"
    assert opts["retry-wait"] == "5"
    assert opts["user-agent"] == "CustomUA/1.0"
    assert opts["referer"] == "http://referer.example.com"
    assert opts["all-proxy"] == "http://proxy.example.com:8080"
    assert opts["checksum"] == "sha-256=abcdef123456"
    assert opts["out"] == "custom_name.zip"
    assert opts["max-download-limit"] == "5M"


def test_parse_aria_flags_repeatable_header_and_opt():
    """Verify repeated --header and --opt flags merge correctly into lists or scalars."""
    tokens = [
        "/aria",
        "--header", "Header-1: Val1",
        "--header", "Header-2: Val2",
        "--opt", "header=Header-3: Val3",
        "--opt", "timeout=30",
        "--opt", "timeout=60",
        "--opt", "max-resume-failure-tries=2",
        "http://example.com/file.zip"
    ]

    opts = _parse_aria_flags(tokens)

    assert opts["header"] == ["Header-1: Val1", "Header-2: Val2", "Header-3: Val3"]
    assert opts["timeout"] == ["30", "60"]
    assert opts["max-resume-failure-tries"] == "2"


def test_parse_aria_flags_speed_fallback():
    """Verify --speed falls back to settings.global_download_speed_limit when omitted."""
    settings.global_download_speed_limit = "20M"
    tokens = ["/aria", "http://example.com/file.zip"]

    opts = _parse_aria_flags(tokens)
    assert opts.get("max-download-limit") == "20M"


@pytest.mark.asyncio
async def test_aria_cmd_ssrf_rejection():
    """Verify /aria rejects private/reserved IP target URLs before job creation."""
    aria_cmd = _get_aria_cmd_handler()

    mock_message = MagicMock()
    mock_message.text = "/aria http://192.168.1.1/private.zip"
    mock_message.caption = None
    mock_message.chat = MagicMock(id=12345)
    mock_message.reply_to_message = None
    mock_message.reply_text = AsyncMock()

    mock_client = MagicMock()

    with patch("app.downloader.direct.core.is_url_private_ip", new_callable=AsyncMock) as mock_ssrf, \
         patch("app.handlers.download._create_and_enqueue_job", new_callable=AsyncMock) as mock_enqueue:

        mock_ssrf.return_value = True
        settings.allow_private_network_urls = False

        await aria_cmd(mock_client, mock_message)

        mock_enqueue.assert_not_called()
        mock_message.reply_text.assert_awaited_once_with(
            "Access to private/internal network URL 'http://192.168.1.1/private.zip' is prohibited."
        )


@pytest.mark.asyncio
async def test_process_download_no_args_regression(tmp_path: Path):
    """Regression test ensuring _process_download handles job.args = None without UnboundLocalError across all 4 dispatch branches."""
    from app.manager.core import JobState, QueueManager

    mock_client = MagicMock()
    mock_store = AsyncMock()

    qm = QueueManager()
    qm.client = mock_client
    qm.store = mock_store

    urls = [
        "magnet:?xt=urn:btih:1234567890abcdef1234567890abcdef12345678",  # torrent
        "mirror:http://example.com/file.zip",                           # mirror
        "direct:http://example.com/file.zip",                           # direct
        "http://example.com/file.zip",                                  # fallback / generic
    ]

    for url in urls:
        mock_job = MagicMock()
        mock_job.id = "test_job_1"
        mock_job.chat_id = 12345
        mock_job.url = url
        mock_job.args = None
        mock_job.status_message_id = None

        job_state = JobState(mock_job, tmp_path)

        with patch("app.downloader.download_torrent_async", new_callable=AsyncMock) as mock_tor, \
             patch("app.downloader.download_direct", new_callable=AsyncMock) as mock_dir, \
             patch("app.downloader.run_with_progress", new_callable=AsyncMock) as mock_gdl, \
             patch("app.manager.core.safe_send", new_callable=AsyncMock), \
             patch("app.manager.core.safe_delete", new_callable=AsyncMock), \
             patch("app.manager.core.safe_pin", new_callable=AsyncMock):

            mock_tor.return_value = DownloadResult(ok=True, files=[])
            mock_dir.return_value = [tmp_path / "file.zip"]
            mock_gdl.return_value = DownloadResult(ok=True, files=[])

            # Must run without throwing UnboundLocalError
            await qm._process_download(job_state)
            assert job_state.downloader_result is not None
            assert job_state.downloader_result.ok is True

