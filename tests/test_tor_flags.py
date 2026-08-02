from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.handlers.download import _parse_flags, register_download_handlers


def _get_tor_cmd_handler() -> callable:
    handlers = []
    mock_app = MagicMock()

    def mock_on_message(filter_obj):
        def decorator(fn):
            # Check if this handler is for the /tor command
            if hasattr(fn, "__name__") and fn.__name__ == "tor_cmd":
                handlers.append(fn)
            return fn
        return decorator

    mock_app.on_message = mock_on_message
    register_download_handlers(mock_app)
    return handlers[0]


def test_parse_flags_magnet_links() -> None:
    """Verify _parse_flags correctly extracts magnet links in various positions."""
    magnet_uri = "magnet:?xt=urn:btih:45A305E26090E543666B6CFA45D6541F486431BD&dn=Ubuntu"

    # Flag before magnet link
    tokens1 = ["/tor", "-m", "-tg", "-uz", "-p", "pass123", magnet_uri]
    is_m, is_tg, uz, pwd, urls = _parse_flags(tokens1)
    assert is_m is True
    assert is_tg is True
    assert uz is True
    assert pwd == "pass123"
    assert urls == [magnet_uri]

    # Magnet link before flags
    tokens2 = ["/tor", magnet_uri, "-m", "-uz", "-p", "pass456"]
    is_m, is_tg, uz, pwd, urls = _parse_flags(tokens2)
    assert is_m is True
    assert is_tg is False
    assert uz is True
    assert pwd == "pass456"
    assert urls == [magnet_uri]


def test_parse_flags_http_regression() -> None:
    """Regression test confirming _parse_flags still handles plain http/https URLs."""
    http_url = "http://example.com/file.iso"
    https_url = "https://example.com/file.zip"

    tokens = ["/direct", "-m", "-tg", http_url, https_url]
    is_m, is_tg, uz, pwd, urls = _parse_flags(tokens)
    assert is_m is True
    assert is_tg is True
    assert uz is False
    assert pwd is None
    assert urls == [http_url, https_url]


@pytest.mark.asyncio
async def test_tor_cmd_handler_with_flags() -> None:
    """Verify tor_cmd handler correctly processes flags and calls _create_and_enqueue_job."""
    tor_cmd = _get_tor_cmd_handler()
    magnet_uri = "magnet:?xt=urn:btih:1234567890ABCDEF1234567890ABCDEF12345678"

    mock_message = MagicMock()
    mock_message.text = f"/tor -m -tg -uz -p mypass {magnet_uri}"
    mock_message.caption = None
    mock_message.chat = MagicMock(id=100200300)
    mock_message.reply_to_message = None
    mock_message.reply_text = AsyncMock()

    mock_client = MagicMock()

    with patch("app.handlers.download._create_and_enqueue_job", new_callable=AsyncMock) as mock_enqueue:
        await tor_cmd(mock_client, mock_message)

        mock_enqueue.assert_awaited_once_with(
            mock_client,
            100200300,
            magnet_uri,
            mock_message,
            magnet_uri[:60] + "..." if len(magnet_uri) > 60 else magnet_uri,
            is_mirror=True,
            upload_tg=True,
            unzip=True,
            password="mypass",
        )


@pytest.mark.asyncio
async def test_tor_cmd_multiple_magnets_rejected() -> None:
    """Verify tor_cmd rejects messages with multiple magnet links with a clear error message."""
    tor_cmd = _get_tor_cmd_handler()
    mag1 = "magnet:?xt=urn:btih:1111111111111111111111111111111111111111"
    mag2 = "magnet:?xt=urn:btih:2222222222222222222222222222222222222222"

    mock_message = MagicMock()
    mock_message.text = f"/tor {mag1} {mag2}"
    mock_message.caption = None
    mock_message.reply_to_message = None
    mock_message.reply_text = AsyncMock()

    mock_client = MagicMock()

    with patch("app.handlers.download._create_and_enqueue_job", new_callable=AsyncMock) as mock_enqueue:
        await tor_cmd(mock_client, mock_message)
        mock_enqueue.assert_not_called()
        mock_message.reply_text.assert_awaited_once_with(
            "Please provide only one magnet link or torrent URL per `/tor` command."
        )
