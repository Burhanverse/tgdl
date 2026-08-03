from __future__ import annotations

import logging
import re
import urllib.parse
from typing import Any

import aiohttp
import feedparser

from ..search import format_bytes

log = logging.getLogger(__name__)


async def search(query: str, limit: int) -> list[dict[str, Any]]:
    """Public torrent search using TorrentGalaxy RSS feed via feedparser."""
    results: list[dict[str, Any]] = []
    encoded_query = urllib.parse.quote(query)
    url = f"https://torrentgalaxy.info/rss?search={encoded_query}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status != 200:
                    log.warning("TorrentGalaxy search returned HTTP status %s", resp.status)
                    return []
                content = await resp.text()

        parsed = feedparser.parse(content)
        if parsed.bozo and not parsed.entries:
            log.warning("TorrentGalaxy feed parse warning: %s", parsed.bozo_exception)

        for entry in parsed.entries[:limit]:
            title = entry.get("title", "").strip()
            if not title:
                continue

            link = entry.get("link", "").strip()
            guid = entry.get("id") or entry.get("guid") or link or "https://torrentgalaxy.info"
            magnet = entry.get("magnet")
            torrent_url = None
            size = entry.get("size") or "N/A"
            seeders = 0
            leechers = 0

            if "seeders" in entry:
                try:
                    seeders = int(entry.seeders)
                except (ValueError, TypeError):
                    pass

            if "leechers" in entry:
                try:
                    leechers = int(entry.leechers)
                except (ValueError, TypeError):
                    pass

            # Inspect enclosures for magnet or direct torrent download link
            for enc in entry.get("enclosures", []):
                href = enc.get("href", "")
                length = enc.get("length", "")

                if href.startswith("magnet:"):
                    magnet = href
                elif href.endswith(".torrent") or "download" in href:
                    torrent_url = href

                if length and str(length).isdigit() and size == "N/A":
                    size = format_bytes(float(length))

            # Inspect summary / description text for fallback magnet or stats regex matching
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

    except Exception as e:
        log.warning("TorrentGalaxy search error: %s", e)

    return results
