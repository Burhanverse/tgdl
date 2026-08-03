from __future__ import annotations

import logging
import urllib.parse
from typing import Any

import aiohttp

from ..search import format_bytes

log = logging.getLogger(__name__)


async def search(query: str, limit: int) -> list[dict[str, Any]]:
    """Free public fallback torrent search using Apibay (PirateBay)."""
    results: list[dict[str, Any]] = []
    encoded_query = urllib.parse.quote(query)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    async with aiohttp.ClientSession(headers=headers) as session:
        try:
            url = f"https://apibay.org/q.php?q={encoded_query}"
            async with session.get(url, timeout=8) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if isinstance(data, list):
                        for item in data[:limit]:
                            name = item.get("name")
                            if not name or name == "No results found":
                                continue
                            info_hash = item.get("info_hash")
                            size = format_bytes(item.get("size", 0))
                            seeders = int(item.get("seeders", 0))
                            leechers = int(item.get("leechers", 0))
                            magnet = (
                                f"magnet:?xt=urn:btih:{info_hash}&dn={urllib.parse.quote(name)}"
                                if info_hash
                                else None
                            )

                            results.append({
                                "name": name,
                                "size": size,
                                "seeders": seeders,
                                "leechers": leechers,
                                "magnet": magnet,
                                "url": f"https://thepiratebay.org/description.php?id={item.get('id')}",
                            })
        except Exception as e:
            log.warning("Apibay search error: %s", e)

    return results
