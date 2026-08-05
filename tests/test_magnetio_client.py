from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import Settings
from app.downloader.aria2c.torrent import (
    SITES,
    MagnetioRPCError,
    initiate_search_tools,
    search_torrents,
)
from app.downloader.aria2c.torrent.magnetio_client import (
    check_health_rpc,
    fetch_providers_rpc,
    format_bytes,
    search_torrents_rpc,
)


def test_format_bytes() -> None:
    assert format_bytes(1024) == "1.00 KB"
    assert format_bytes(1048576) == "1.00 MB"
    assert format_bytes(1073741824) == "1.00 GB"
    assert format_bytes("invalid") == "N/A"


@pytest.mark.asyncio
async def test_search_torrents_rpc_success() -> None:
    mock_rpc_response = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "count": 1,
            "torrents": [
                {
                    "title": "Ubuntu 22.04 ISO",
                    "infoHash": "45a305e26090e543666b6cfa45d6541f486431bd",
                    "seeders": 120,
                    "leechers": 5,
                    "size": 3500000000,
                    "provider": "ThePirateBay",
                    "magnet": "magnet:?xt=urn:btih:45a305e26090e543666b6cfa45d6541f486431bd",
                }
            ],
        },
    }

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=mock_rpc_response)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        results = await search_torrents_rpc("Ubuntu", limit=10)

    assert len(results) == 1
    assert results[0]["name"] == "Ubuntu 22.04 ISO"
    assert results[0]["seeders"] == 120
    assert results[0]["provider"] == "ThePirateBay"
    assert "45a305e26090e543666b6cfa45d6541f486431bd" in results[0]["magnet"]


@pytest.mark.asyncio
async def test_search_torrents_rpc_jsonrpc_error() -> None:
    mock_rpc_response = {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {
            "code": -32001,
            "message": "Unauthorized",
        },
    }

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=mock_rpc_response)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        with pytest.raises(MagnetioRPCError) as exc_info:
            await search_torrents_rpc("Ubuntu")

    assert exc_info.value.code == -32001
    assert "Unauthorized" in str(exc_info.value)


@pytest.mark.asyncio
async def test_search_torrents_rpc_http_error() -> None:
    mock_resp = MagicMock()
    mock_resp.status = 500
    mock_resp.text = AsyncMock(return_value="Internal Server Error")
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        with pytest.raises(MagnetioRPCError):
            await search_torrents_rpc("Ubuntu")


@pytest.mark.asyncio
async def test_fetch_providers_rpc() -> None:
    mock_rpc_response = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "providers": [
                {"id": "thepiratebay", "name": "ThePirateBay"},
                {"id": "yts", "name": "YTS"},
            ]
        },
    }

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=mock_rpc_response)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        providers = await fetch_providers_rpc()

    assert len(providers) == 2
    assert providers[0]["id"] == "thepiratebay"


@pytest.mark.asyncio
async def test_check_health_rpc() -> None:
    mock_rpc_response = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"status": "ok", "service": "magnetio-scraper"},
    }

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=mock_rpc_response)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        healthy = await check_health_rpc()

    assert healthy is True


@pytest.mark.asyncio
async def test_initiate_search_tools_populates_sites() -> None:
    with patch("app.downloader.aria2c.torrent.search.check_health_rpc", return_value=True), \
         patch("app.downloader.aria2c.torrent.search.fetch_providers_rpc", return_value=[{"id": "tpb", "name": "ThePirateBay"}]):
        await initiate_search_tools()

    from app.downloader.aria2c.torrent.search import SITES
    assert SITES is not None
    assert "tpb" in SITES
    assert SITES["tpb"] == "ThePirateBay"
    assert "all" in SITES
