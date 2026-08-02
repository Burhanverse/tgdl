from __future__ import annotations

import logging
import urllib.parse
from typing import Any

import aiohttp

log = logging.getLogger(__name__)


async def search(query: str, limit: int) -> list[dict[str, Any]]:
    """Public torrent search using YTS JSON API."""
    results: list[dict[str, Any]] = []
    encoded_query = urllib.parse.quote(query)
    url = f"https://yts.mx/api/v2/list_movies.json?query_term={encoded_query}&limit={limit}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status != 200:
                    log.warning("YTS search returned HTTP status %s", resp.status)
                    return []
                payload = await resp.json()

        data = payload.get("data") or {}
        movies = data.get("movies") or []
        if not isinstance(movies, list):
            return []

        for movie in movies:
            title = movie.get("title") or "Unknown"
            year = movie.get("year")
            slug = movie.get("slug") or ""
            movie_url = movie.get("url") or (f"https://yts.mx/movies/{slug}" if slug else "https://yts.mx")
            quoted_title = urllib.parse.quote(title)

            torrents = movie.get("torrents") or []
            if not isinstance(torrents, list):
                continue

            for torrent in torrents:
                quality = torrent.get("quality") or "HD"
                name_variant = f"{title} ({year}) [{quality}]" if year else f"{title} [{quality}]"
                info_hash = torrent.get("hash")
                magnet = (
                    f"magnet:?xt=urn:btih:{info_hash}&dn={quoted_title}"
                    if info_hash
                    else None
                )
                size = torrent.get("size") or "N/A"
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

    except Exception as e:
        log.warning("YTS search error: %s", e)

    return results
