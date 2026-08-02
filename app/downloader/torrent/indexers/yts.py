from __future__ import annotations

import asyncio
import logging
import re
import urllib.parse
from typing import Any

import aiohttp
import feedparser

from app.config import settings
from ..search import format_bytes

log = logging.getLogger(__name__)

DEFAULT_API_DOMAIN = "movies-api.accel.li"
RSS_URL = "https://yts.gg/rss"

_YTS_TRACKERS: list[str] = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://tracker.dler.org:6969/announce",
    "udp://open.stealth.si:80/announce",
    "udp://open.demonii.com:1337/announce",
    "https://tracker.moeblog.cn:443/announce",
    "udp://open.dstud.io:6969/announce",
    "udp://tracker.srv00.com:6969/announce",
    "https://tracker.zhuqiy.com:443/announce",
    "https://tracker.pmman.tech:443/announce",
]


def _build_magnet(info_hash: str, title: str) -> str:
    """Builds a BitTorrent magnet link with infohash, display name, and YTS trackers."""
    quoted_title = urllib.parse.quote(title)
    magnet = f"magnet:?xt=urn:btih:{info_hash}&dn={quoted_title}"
    for tracker in _YTS_TRACKERS:
        magnet += f"&tr={urllib.parse.quote(tracker)}"
    return magnet


def _format_torrent_name(title: str, year: Any, quality: Any, type_name: Any) -> str:
    """Formats a torrent result name variant from movie title, year, quality, and release type."""
    q_str = str(quality).strip() if quality else "HD"
    if type_name:
        q_str = f"{q_str} {type_name}".strip()
    return f"{title} ({year}) [{q_str}]" if year else f"{title} [{q_str}]"


def _parse_api_movie(movie: dict[str, Any], api_domain: str) -> list[dict[str, Any]]:
    """Transforms a single YTS API movie dictionary into standard indexer result dictionaries."""
    results: list[dict[str, Any]] = []
    title = movie.get("title") or movie.get("title_english") or "Unknown"
    year = movie.get("year")
    slug = movie.get("slug") or ""
    movie_url = movie.get("url") or (
        f"https://yts.gg/movies/{slug}" if slug else f"https://{api_domain}"
    )

    torrents = movie.get("torrents")
    if not isinstance(torrents, list):
        return results

    for torrent in torrents:
        if not isinstance(torrent, dict):
            continue

        quality = torrent.get("quality")
        type_name = torrent.get("type")
        name_variant = _format_torrent_name(title, year, quality, type_name)

        size_bytes = torrent.get("size_bytes")
        size = torrent.get("size") or (
            format_bytes(float(size_bytes)) if size_bytes else "N/A"
        )
        seeders = int(torrent.get("seeds", 0))
        leechers = int(torrent.get("peers", 0))
        torrent_download_url = torrent.get("url")

        results.append({
            "name": name_variant,
            "size": size,
            "seeders": seeders,
            "leechers": leechers,
            "magnet": None,
            "torrent": torrent_download_url,
            "url": movie_url,
        })

    return results


def _parse_yts_rss(content: str, query: str, limit: int) -> list[dict[str, Any]]:
    """Parses YTS RSS XML feed (https://yts.gg/rss) using feedparser."""
    results: list[dict[str, Any]] = []
    parsed = feedparser.parse(content)
    if parsed.bozo and not parsed.entries:
        return []

    query_words = [w.lower() for w in query.split() if w]

    for entry in parsed.entries:
        title = entry.get("title", "").strip()
        if not title:
            continue

        if query_words and not all(w in title.lower() for w in query_words):
            continue

        link = entry.get("link", "").strip() or "https://yts.gg"
        guid = entry.get("id") or entry.get("guid") or link
        magnet = entry.get("magnet")
        torrent_url = None
        size = entry.get("size") or "N/A"
        seeders = 0
        leechers = 0

        for enc in entry.get("enclosures", []):
            href = enc.get("href", "")
            length = enc.get("length", "")
            if href.startswith("magnet:"):
                magnet = href
            elif ".torrent" in href or "/torrent/" in href or "download" in href:
                torrent_url = href

            if length and str(length).isdigit() and size == "N/A" and int(length) > 10000:
                size = format_bytes(float(length))

        summary = entry.get("summary") or entry.get("description") or ""
        if summary:
            if not magnet:
                mag_match = re.search(r'magnet:\?xt=urn:btih:[a-zA-Z0-9]+[^\s"\'<>]*', summary)
                if mag_match:
                    magnet = mag_match.group(0)

            if seeders == 0:
                s_match = re.search(r"(?:Seeders?|Seeds?|S):\s*(\d+)", summary, re.IGNORECASE)
                if s_match:
                    seeders = int(s_match.group(1))

            if leechers == 0:
                l_match = re.search(r"(?:Leechers?|Leech|L):\s*(\d+)", summary, re.IGNORECASE)
                if l_match:
                    leechers = int(l_match.group(1))

            if size == "N/A":
                size_match = re.search(r"Size:\s*([\d\.]+\s*[KMGT]B)", summary, re.IGNORECASE)
                if size_match:
                    size = size_match.group(1)

        results.append({
            "name": title,
            "size": size,
            "seeders": seeders,
            "leechers": leechers,
            "magnet": magnet,
            "torrent": torrent_url,
            "url": guid,
        })

        if len(results) >= limit:
            break

    return results


async def _search_api(
    query: str, limit: int, api_domain: str, headers: dict[str, str]
) -> list[dict[str, Any]] | None:
    """Attempts to fetch search results from the YTS REST API (v2).

    Returns list of results on success (or empty list if no movies match), or None if the API call fails or status is not ok.
    """
    encoded_query = urllib.parse.quote(query)
    api_limit = min(limit, 50)
    json_url = f"https://{api_domain}/api/v2/list_movies.json?query_term={encoded_query}&limit={api_limit}"

    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(json_url, timeout=10) as resp:
                if resp.status != 200:
                    log.warning("YTS API (%s) returned HTTP status %s", api_domain, resp.status)
                    return None

                payload = await resp.json()
                if not isinstance(payload, dict):
                    log.warning("YTS API (%s) returned invalid non-dict JSON response", api_domain)
                    return None

                status = payload.get("status")
                if status != "ok":
                    log.warning(
                        "YTS API (%s) status is not ok (%r): %s",
                        api_domain,
                        status,
                        payload.get("status_message"),
                    )
                    return None

                data = payload.get("data")
                if not isinstance(data, dict):
                    log.info("YTS search API (%s) returned ok status with empty data", api_domain)
                    return []

                movies = data.get("movies")
                if not isinstance(movies, list):
                    log.info("YTS search API (%s) found 0 movies for query %r", api_domain, query)
                    return []

                log.info("YTS search succeeded using official API (%s)", api_domain)
                results: list[dict[str, Any]] = []
                for movie in movies:
                    if isinstance(movie, dict):
                        movie_results = _parse_api_movie(movie, api_domain)
                        for item in movie_results:
                            results.append(item)
                            if len(results) >= limit:
                                return results

                return results
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
        log.info("YTS API (%s) failed connection: %s", api_domain, e)
        return None
    except Exception as e:
        log.warning("YTS API (%s) processing error: %s", api_domain, e)
        return None


async def _search_rss(
    query: str, limit: int, headers: dict[str, str]
) -> list[dict[str, Any]]:
    """Attempts to fetch search results using the official YTS RSS feed (https://yts.gg/rss)."""
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(RSS_URL, timeout=10) as resp:
                if resp.status == 200:
                    xml_content = await resp.text()
                    parsed_rss = _parse_yts_rss(xml_content, query, limit)
                    log.info("YTS search succeeded using RSS feed (%s)", RSS_URL)
                    return parsed_rss
                else:
                    log.warning("YTS RSS feed (%s) returned HTTP status %s", RSS_URL, resp.status)
    except Exception as e:
        log.warning("YTS RSS feed (%s) failed: %s", RSS_URL, e)

    return []


async def search(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Public torrent search using official YTS API (movies-api.accel.li) with fallback to https://yts.gg/rss."""
    query = query.strip()
    if not query:
        return []

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    api_domain = settings.yts_mirror_domain or DEFAULT_API_DOMAIN

    # 1. Try official API first
    api_results = await _search_api(query, limit, api_domain, headers)
    if api_results is not None:
        return api_results

    # 2. Try RSS feed fallback if API call failed
    return await _search_rss(query, limit, headers)
