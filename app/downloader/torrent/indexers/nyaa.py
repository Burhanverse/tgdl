from __future__ import annotations

import logging
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any

import aiohttp

log = logging.getLogger(__name__)


async def search(query: str, limit: int) -> list[dict[str, Any]]:
    """Public torrent search using Nyaa RSS feed."""
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

        try:
            root = ET.fromstring(content)
        except ET.ParseError as pe:
            log.warning("Nyaa search XML parse error: %s", pe)
            return []

        channel = root.find("channel")
        if channel is None:
            return []

        items = channel.findall("item")
        for item in items[:limit]:
            title = ""
            link = ""
            guid = ""
            size = "N/A"
            seeders = 0
            leechers = 0
            info_hash = ""

            for child in item:
                tag_name = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                text = (child.text or "").strip()

                if tag_name == "title":
                    title = text
                elif tag_name == "link":
                    link = text
                elif tag_name == "guid":
                    guid = text
                elif tag_name == "size":
                    size = text
                elif tag_name == "seeders":
                    try:
                        seeders = int(text)
                    except ValueError:
                        seeders = 0
                elif tag_name == "leechers":
                    try:
                        leechers = int(text)
                    except ValueError:
                        leechers = 0
                elif tag_name == "infoHash":
                    info_hash = text

            if not title:
                continue

            magnet = (
                f"magnet:?xt=urn:btih:{info_hash}&dn={urllib.parse.quote(title)}"
                if info_hash
                else None
            )
            torrent_url = link if (link and not link.startswith("magnet:")) else None
            info_url = guid or link or "https://nyaa.si"

            results.append({
                "name": title,
                "size": size or "N/A",
                "seeders": seeders,
                "leechers": leechers,
                "magnet": magnet,
                "torrent": torrent_url,
                "url": info_url,
            })

    except Exception as e:
        log.warning("Nyaa search error: %s", e)

    return results
