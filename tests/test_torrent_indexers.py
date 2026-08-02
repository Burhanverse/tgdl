from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import Settings
from app.downloader.torrent.indexers import (
    INDEXERS,
    dedupe_key,
    extract_info_hash,
    run_enabled_indexers,
)
from app.downloader.torrent.indexers import apibay, nyaa, torrents_csv, yts


def test_indexers_registry() -> None:
    assert "apibay" in INDEXERS
    assert "torrents_csv" in INDEXERS
    assert "nyaa" in INDEXERS
    assert "yts" in INDEXERS



def test_extract_info_hash() -> None:
    magnet = "magnet:?xt=urn:btih:45a305e26090e543666b6cfa45d6541f486431bd&dn=Ubuntu"
    assert extract_info_hash(magnet) == "45A305E26090E543666B6CFA45D6541F486431BD"
    assert extract_info_hash("invalid_magnet") is None
    assert extract_info_hash(None) is None


def test_dedupe_key() -> None:
    item_with_magnet = {
        "name": "Ubuntu 22.04",
        "size": "3.5 GB",
        "magnet": "magnet:?xt=urn:btih:45A305E26090E543666B6CFA45D6541F486431BD&dn=Ubuntu",
    }
    assert dedupe_key(item_with_magnet) == "45A305E26090E543666B6CFA45D6541F486431BD"

    item_without_magnet = {
        "name": "  Ubuntu 22.04  ",
        "size": "3.5 GB",
        "magnet": None,
    }
    assert dedupe_key(item_without_magnet) == ("ubuntu 22.04", "3.5 GB")


@pytest.mark.asyncio
async def test_apibay_search() -> None:
    mock_data = [
        {
            "id": "123",
            "name": "Test Linux ISO",
            "info_hash": "45A305E26090E543666B6CFA45D6541F486431BD",
            "size": "1073741824",
            "seeders": "100",
            "leechers": "10",
        }
    ]

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=mock_data)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        results = await apibay.search("linux", limit=10)

    assert len(results) == 1
    assert results[0]["name"] == "Test Linux ISO"
    assert results[0]["seeders"] == 100
    assert "45A305E26090E543666B6CFA45D6541F486431BD" in results[0]["magnet"]


@pytest.mark.asyncio
async def test_torrents_csv_search() -> None:
    mock_data = {
        "torrents": [
            {
                "name": "CSV Test Release",
                "infohash": "ABC123DEF456",
                "size": 500000000,
                "seeders": 50,
                "leechers": 5,
            }
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=mock_data)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        results = await torrents_csv.search("test", limit=10)

    assert len(results) == 1
    assert results[0]["name"] == "CSV Test Release"
    assert results[0]["seeders"] == 50


@pytest.mark.asyncio
async def test_nyaa_search() -> None:
    xml_content = """<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0" xmlns:nyaa="https://nyaa.si/xmlns/nyaa">
      <channel>
        <title>Nyaa - RSS</title>
        <item>
          <title>[SubsPlease] Anime Episode 01 (1080p)</title>
          <link>https://nyaa.si/download/1001.torrent</link>
          <guid>https://nyaa.si/view/1001</guid>
          <nyaa:size>1.2 GiB</nyaa:size>
          <nyaa:seeders>350</nyaa:seeders>
          <nyaa:leechers>12</nyaa:leechers>
          <nyaa:infoHash>11223344556677889900aabbccddeeff11223344</nyaa:infoHash>
        </item>
      </channel>
    </rss>"""

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.text = AsyncMock(return_value=xml_content)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        results = await nyaa.search("anime", limit=10)

    assert len(results) == 1
    assert results[0]["name"] == "[SubsPlease] Anime Episode 01 (1080p)"
    assert results[0]["size"] == "1.2 GiB"
    assert results[0]["seeders"] == 350
    assert results[0]["torrent"] == "https://nyaa.si/download/1001.torrent"
    assert "11223344556677889900aabbccddeeff11223344" in results[0]["magnet"]


@pytest.mark.asyncio
async def test_yts_search() -> None:
    json_data = {
        "status": "ok",
        "data": {
            "movie_count": 1,
            "movies": [
                {
                    "title": "Inception",
                    "year": 2010,
                    "slug": "inception-2010",
                    "url": "https://yts.mx/movies/inception-2010",
                    "torrents": [
                        {
                            "url": "https://yts.mx/torrent/download/1080p",
                            "hash": "FEEDFACE1234567890",
                            "quality": "1080p",
                            "seeds": 800,
                            "peers": 40,
                            "size": "2.1 GB",
                        }
                    ],
                }
            ],
        },
    }

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=json_data)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        results = await yts.search("Inception", limit=10)

    assert len(results) == 1
    assert results[0]["name"] == "Inception (2010) [1080p]"
    assert results[0]["size"] == "2.1 GB"
    assert results[0]["seeders"] == 800
    assert "FEEDFACE1234567890" in results[0]["magnet"]


@pytest.mark.asyncio
async def test_run_enabled_indexers_concurrency_dedupe_sorting() -> None:
    async def mock_indexer_a(query: str, limit: int) -> list[dict[str, Any]]:
        return [
            {
                "name": "Shared Release",
                "size": "1 GB",
                "seeders": 10,
                "leechers": 1,
                "magnet": "magnet:?xt=urn:btih:HASH12345&dn=Shared",
            },
            {
                "name": "Low Seed Release",
                "size": "500 MB",
                "seeders": 2,
                "leechers": 0,
                "magnet": "magnet:?xt=urn:btih:HASH99999&dn=Low",
            },
        ]

    async def mock_indexer_b(query: str, limit: int) -> list[dict[str, Any]]:
        return [
            {
                "name": "Shared Release Duplicate",
                "size": "1 GB",
                "seeders": 10,
                "leechers": 1,
                "magnet": "magnet:?xt=urn:btih:HASH12345&dn=Shared",
            },
            {
                "name": "High Seed Release",
                "size": "2 GB",
                "seeders": 500,
                "leechers": 20,
                "magnet": "magnet:?xt=urn:btih:HASH77777&dn=High",
            },
        ]

    async def mock_indexer_failing(query: str, limit: int) -> list[dict[str, Any]]:
        raise RuntimeError("Indexer network timeout")

    with patch.dict(
        INDEXERS,
        {
            "mock_a": mock_indexer_a,
            "mock_b": mock_indexer_b,
            "mock_fail": mock_indexer_failing,
        },
        clear=False,
    ):
        results = await run_enabled_indexers(
            query="test",
            limit=5,
            enabled_names=["mock_a", "mock_b", "mock_fail"],
        )

    # Should deduplicate Shared Release (HASH12345) -> 3 total items unique -> sorted by seeders desc
    assert len(results) == 3
    assert results[0]["name"] == "High Seed Release"
    assert results[0]["seeders"] == 500
    assert results[1]["seeders"] == 10
    assert results[2]["seeders"] == 2


def test_config_torrent_public_indexers() -> None:
    s = Settings(torrent_public_indexers="apibay, nyaa, yts")
    assert s.torrent_public_indexers == ["apibay", "nyaa", "yts"]

    s_default = Settings()
    assert s_default.torrent_public_indexers == ["apibay", "torrents_csv", "nyaa", "yts"]


def test_format_search_results_html_escaping() -> None:
    from app.downloader.torrent.search import format_search_results_html

    results = [
        {
            "name": "<script>alert('xss')</script> Test Release",
            "size": "1.2 GB & special",
            "seeders": 100,
            "leechers": 10,
            "magnet": "magnet:?xt=urn:btih:1234567890ABCDEF&dn=Test",
            "torrent": "https://example.com/download.torrent?id=1&name=test",
        }
    ]

    html_out = format_search_results_html(results, query="<query>", site="public")
    assert "&lt;script&gt;" in html_out
    assert "<script>" not in html_out
    assert "&lt;query&gt;" in html_out


@pytest.mark.asyncio
async def test_yts_mirror_fallback_on_connection_error() -> None:
    """Verifies that if the first mirror raises a connection error, the second mirror is tried."""
    import aiohttp
    from app.downloader.torrent.indexers import yts

    json_data = {
        "status": "ok",
        "data": {
            "movie_count": 1,
            "movies": [
                {
                    "title": "Fallback Movie",
                    "year": 2024,
                    "slug": "fallback-movie-2024",
                    "torrents": [
                        {
                            "url": "https://yts.lt/torrent/download/1080p",
                            "hash": "HASH12345",
                            "quality": "1080p",
                            "seeds": 10,
                            "peers": 2,
                            "size": "1.5 GB",
                        }
                    ],
                }
            ],
        },
    }

    rss_xml = """<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0">
      <channel>
        <title>RSS for YTS.GG</title>
        <item>
          <title><![CDATA[Fallback Movie (2024) [1080p]]]></title>
          <link>https://yts.gg/movies/fallback-movie-2024</link>
          <guid>https://yts.gg/movies/fallback-movie-2024#1080p</guid>
          <enclosure url="https://yts.gg/torrent/download/HASH12345" type="application/x-bittorrent" length="10000"/>
        </item>
      </channel>
    </rss>"""

    mock_resp_success = MagicMock()
    mock_resp_success.status = 200
    mock_resp_success.json = AsyncMock(return_value=json_data)
    mock_resp_success.text = AsyncMock(return_value=rss_xml)
    mock_resp_success.__aenter__ = AsyncMock(return_value=mock_resp_success)
    mock_resp_success.__aexit__ = AsyncMock(return_value=None)

    call_urls = []

    def mock_get(url, timeout=10):
        call_urls.append(url)
        if "movies-api.accel.li" in url:
            raise aiohttp.ClientConnectorError(connection_key=MagicMock(), os_error=OSError("DNS failure"))
        return mock_resp_success

    mock_session = MagicMock()
    mock_session.get = MagicMock(side_effect=mock_get)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        results = await yts.search("Fallback", limit=10)

    assert len(results) == 1
    assert results[0]["name"] == "Fallback Movie (2024) [1080p]"
    assert len(call_urls) == 2
    assert "movies-api.accel.li" in call_urls[0]
    assert call_urls[1] == "https://yts.gg/rss"


@pytest.mark.asyncio
async def test_yts_search_empty_result_does_not_fall_through() -> None:
    """Verifies that an empty valid result on a working mirror is returned and does not fall through."""
    from app.downloader.torrent.indexers import yts

    empty_json = {"status": "ok", "data": {"movie_count": 0, "movies": []}}

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=empty_json)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=None)

    call_urls = []

    def mock_get(url, timeout=10):
        call_urls.append(url)
        return mock_resp

    mock_session = MagicMock()
    mock_session.get = MagicMock(side_effect=mock_get)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        results = await yts.search("NonExistentMovie12345", limit=10)

    assert results == []
    assert len(call_urls) == 1
    assert "movies-api.accel.li" in call_urls[0]


@pytest.mark.asyncio
async def test_yts_search_config_override() -> None:
    """Verifies that yts_mirror_domain config override prioritizes custom domain."""
    from app.config import settings
    from app.downloader.torrent.indexers import yts

    json_data = {"status": "ok", "data": {"movies": []}}

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=json_data)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=None)

    call_urls = []

    def mock_get(url, timeout=10):
        call_urls.append(url)
        return mock_resp

    mock_session = MagicMock()
    mock_session.get = MagicMock(side_effect=mock_get)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch.object(settings, "yts_mirror_domain", "custom-yts.org"), \
         patch("aiohttp.ClientSession", return_value=mock_session):
        results = await yts.search("Test", limit=10)

    assert results == []
    assert len(call_urls) == 1
    assert "custom-yts.org" in call_urls[0]


@pytest.mark.asyncio
async def test_yts_rss_fallback() -> None:
    """Verifies that if JSON API returns 404, RSS feed fallback (e.g. yts.gg/rss) is used."""
    from app.downloader.torrent.indexers import yts

    rss_xml = """<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0">
      <channel>
        <title>RSS for YTS.GG</title>
        <item>
          <title><![CDATA[Possessed (1931) [1080p] [BluRay]]]></title>
          <link>https://yts.gg/movies/possessed-1931</link>
          <guid>https://yts.gg/movies/possessed-1931#1080p.blu</guid>
          <enclosure url="https://yts.gg/torrent/download/949CA5ABE25C3E915DD82A3A8BE39EFE0FA879EC" type="application/x-bittorrent" length="10000"/>
          <description><![CDATA[Size: 1.27 GB<br />IMDB Rating: 6.9/10]]></description>
        </item>
      </channel>
    </rss>"""

    mock_resp_404 = MagicMock()
    mock_resp_404.status = 404
    mock_resp_404.__aenter__ = AsyncMock(return_value=mock_resp_404)
    mock_resp_404.__aexit__ = AsyncMock(return_value=None)

    mock_resp_rss = MagicMock()
    mock_resp_rss.status = 200
    mock_resp_rss.text = AsyncMock(return_value=rss_xml)
    mock_resp_rss.__aenter__ = AsyncMock(return_value=mock_resp_rss)
    mock_resp_rss.__aexit__ = AsyncMock(return_value=None)

    call_urls = []

    def mock_get(url, timeout=10):
        call_urls.append(url)
        if "api/v2" in url:
            return mock_resp_404
        return mock_resp_rss

    mock_session = MagicMock()
    mock_session.get = MagicMock(side_effect=mock_get)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        results = await yts.search("Possessed", limit=10)

    assert len(results) == 1
    assert results[0]["name"] == "Possessed (1931) [1080p] [BluRay]"
    assert "949CA5ABE25C3E915DD82A3A8BE39EFE0FA879EC" in results[0]["magnet"]
    assert any("/rss" in u for u in call_urls)


def test_parse_yts_rss_user_format() -> None:
    from app.downloader.torrent.indexers.yts import _parse_yts_rss

    xml_content = """<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0">
      <channel>
        <title>RSS for YTS.GG - YTS.BZ (old YTS.MX) - Feed</title>
        <item>
          <title><![CDATA[ Chop Suey (2001) [720p] [WEBRip] [YTS.GG-YTS.BZ] ]]></title>
          <description><![CDATA[ <a href="https://yts.gg/movies/chop-suey-2001"><img src="https://img.yts.gg/assets/images/movies/chop_suey_2001/medium-cover.jpg" alt="Chop Suey (2001)" /></a><br />IMDB Rating: 6.6/10<br />Genre: Biography / Documentary<br />Size: 904.5 MB<br />Runtime: 1hr 38 min<br /><br />A homage to Bruce Weber's Favourite things. ]]></description>
          <link>https://yts.gg/movies/chop-suey-2001</link>
          <guid>https://yts.gg/movies/chop-suey-2001#720p.web</guid>
          <pubDate>Sun, 02 Aug 2026 07:51:16 +0200</pubDate>
          <enclosure url="https://yts.gg/torrent/download/42C91BA97A65A063535B98C0AB7FE8778AE51E73" type="application/x-bittorrent" length="10000"/>
        </item>
      </channel>
    </rss>"""

    results = _parse_yts_rss(xml_content, query="Chop Suey", limit=5)
    assert len(results) == 1
    item = results[0]
    assert item["name"] == "Chop Suey (2001) [720p] [WEBRip] [YTS.GG-YTS.BZ]"
    assert item["size"] == "904.5 MB"
    assert "42C91BA97A65A063535B98C0AB7FE8778AE51E73" in item["magnet"]
    assert item["torrent"] == "https://yts.gg/torrent/download/42C91BA97A65A063535B98C0AB7FE8778AE51E73"
    assert item["url"] == "https://yts.gg/movies/chop-suey-2001#720p.web"

