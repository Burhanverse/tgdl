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

API_DOMAIN = "movies-api.accel.li"
RSS_URL = "https://yts.gg/rss"


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
            elif ".torrent" in href or "/torrent/download/" in href or "download" in href:
                torrent_url = href
                if not magnet:
                    hash_match = re.search(r"/torrent/download/([a-fA-F0-9]{40})", href)
                    if hash_match:
                        info_hash = hash_match.group(1)
                        magnet = f"magnet:?xt=urn:btih:{info_hash}&dn={urllib.parse.quote(title)}"

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


async def search(query: str, limit: int) -> list[dict[str, Any]]:
    """Public torrent search using official YTS API (movies-api.accel.li) with fallback to https://yts.gg/rss."""
    results: list[dict[str, Any]] = []
    encoded_query = urllib.parse.quote(query)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    api_domain = settings.yts_mirror_domain or API_DOMAIN
    json_url = f"https://{api_domain}/api/v2/list_movies.json?query_term={encoded_query}&limit={limit}"

    # 1. Try API first (movies-api.accel.li or user configured domain)
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(json_url, timeout=10) as resp:
                if resp.status == 200:
                    payload = await resp.json()
                    data = payload.get("data") or {}
                    movies = data.get("movies") or []
                    if isinstance(movies, list):
                        log.info("YTS search succeeded using official API (%s)", api_domain)
                        for movie in movies:
                            title = movie.get("title") or "Unknown"
                            year = movie.get("year")
                            slug = movie.get("slug") or ""
                            movie_url = movie.get("url") or (f"https://yts.gg/movies/{slug}" if slug else f"https://{api_domain}")
                            quoted_title = urllib.parse.quote(title)

                            torrents = movie.get("torrents") or []
                            if not isinstance(torrents, list):
                                continue

                            for torrent in torrents:
                                quality = torrent.get("quality") or "HD"
                                type_name = torrent.get("type")
                                quality_str = f"{quality} {type_name}".strip() if type_name else quality
                                name_variant = f"{title} ({year}) [{quality_str}]" if year else f"{title} [{quality_str}]"
                                info_hash = torrent.get("hash")
                                magnet = (
                                    f"magnet:?xt=urn:btih:{info_hash}&dn={quoted_title}"
                                    if info_hash
                                    else None
                                )
                                size_bytes = torrent.get("size_bytes")
                                size = torrent.get("size") or (format_bytes(float(size_bytes)) if size_bytes else "N/A")
                                seeders = int(torrent.get("seeds", 0))
                                leechers = int(torrent.get("peers", 0))
                                torrent_download_url = torrent.get("url")

                                results.append({
                                    "name": name_variant,
                                    "size": size,
                                    "seeders": seeders,
                                    "leechers": leechers,
                                    "magnet": magnet,
                                    "torrent": torrent_download_url,
                                    "url": movie_url,
                                })

                                if len(results) >= limit:
                                    break

                            if len(results) >= limit:
                                break

                        return results
                else:
                    log.warning("YTS API (%s) returned HTTP status %s", api_domain, resp.status)
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
        log.info("YTS API (%s) failed connection: %s, falling back to RSS", api_domain, e)
    except Exception as e:
        log.warning("YTS API (%s) processing error: %s", api_domain, e)

    # 2. Try official RSS feed fallback (https://yts.gg/rss)
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
