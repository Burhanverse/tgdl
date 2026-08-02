from __future__ import annotations

import logging
import urllib.parse
from typing import Any

import aiohttp
import feedparser

log = logging.getLogger(__name__)


async def search(query: str, limit: int) -> list[dict[str, Any]]:
    """Public torrent search using Nyaa RSS feed via feedparser."""
    results: list[dict[str, Any]] = []
    encoded_query = urllib.parse.quote(query)
    url = f"https://nyaa.si/?page=rss&q={encoded_query}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status != 200:
                    log.warning("Nyaa search returned HTTP status %s", resp.status)
                    return []
                content = await resp.text()

        parsed = feedparser.parse(content)
        if parsed.bozo and not parsed.entries:
            log.warning("Nyaa search feed parse warning: %s", parsed.bozo_exception)

        for entry in parsed.entries[:limit]:
            title = entry.get("title", "").strip()
            if not title:
                continue

            link = entry.get("link", "").strip()
            guid = entry.get("id") or entry.get("guid") or link or "https://nyaa.si"
            size = entry.get("nyaa_size") or "N/A"

            try:
                seeders = int(entry.get("nyaa_seeders", 0))
            except (ValueError, TypeError):
                seeders = 0

            try:
                leechers = int(entry.get("nyaa_leechers", 0))
            except (ValueError, TypeError):
                leechers = 0

            info_hash = entry.get("nyaa_infohash") or entry.get("infohash") or ""
            magnet = (
                f"magnet:?xt=urn:btih:{info_hash}&dn={urllib.parse.quote(title)}"
                if info_hash
                else None
            )
            torrent_url = link if (link and not link.startswith("magnet:")) else None

            results.append({
                "name": title,
                "size": size,
                "seeders": seeders,
                "leechers": leechers,
                "magnet": magnet,
                "torrent": torrent_url,
                "url": guid,
            })

    except Exception as e:
        log.warning("Nyaa search error: %s", e)

    return results
