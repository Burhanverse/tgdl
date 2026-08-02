from __future__ import annotations

import logging
import re
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any

import aiohttp

from ..search import format_bytes

log = logging.getLogger(__name__)


async def search(query: str, limit: int) -> list[dict[str, Any]]:
    """Public torrent search using TorrentGalaxy RSS feed."""
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

        try:
            root = ET.fromstring(content)
        except ET.ParseError as pe:
            log.warning("TorrentGalaxy search XML parse error: %s", pe)
            return []

        channel = root.find("channel")
        if channel is None:
            return []

        items = channel.findall("item")
        for item in items[:limit]:
            title = ""
            link = ""
            guid = ""
            magnet = None
            torrent_url = None
            size = "N/A"
            seeders = 0
            leechers = 0

            for child in item:
                tag_name = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                text = (child.text or "").strip()

                if tag_name == "title":
                    title = text
                elif tag_name == "link":
                    link = text
                elif tag_name == "guid":
                    guid = text
                elif tag_name == "magnet":
                    magnet = text
                elif tag_name == "seeders":
                    try:
                        seeders = int(text)
                    except ValueError:
                        pass
                elif tag_name == "leechers":
                    try:
                        leechers = int(text)
                    except ValueError:
                        pass
                elif tag_name == "size":
                    size = text
                elif tag_name == "enclosure":
                    enc_url = child.attrib.get("url", "")
                    enc_len = child.attrib.get("length", "")
                    if enc_url.startswith("magnet:"):
                        magnet = enc_url
                    elif enc_url.endswith(".torrent") or "download" in enc_url:
                        torrent_url = enc_url

                    if enc_len and enc_len.isdigit() and size == "N/A":
                        size = format_bytes(float(enc_len))
                elif tag_name == "description":
                    # Extract magnet or stats from description if not found in child tags
                    if not magnet:
                        mag_match = re.search(r'magnet:\?xt=urn:btih:[a-zA-Z0-9]+[^\s"\'<>]*', text)
                        if mag_match:
                            magnet = mag_match.group(0)

                    if seeders == 0:
                        s_match = re.search(r"(?:Seeders?|Seeds?|S):\s*(\d+)", text, re.IGNORECASE)
                        if s_match:
                            seeders = int(s_match.group(1))

                    if leechers == 0:
                        l_match = re.search(r"(?:Leechers?|Leech|L):\s*(\d+)", text, re.IGNORECASE)
                        if l_match:
                            leechers = int(l_match.group(1))

                    if size == "N/A":
                        size_match = re.search(r"Size:\s*([\d\.]+\s*[KMGT]B)", text, re.IGNORECASE)
                        if size_match:
                            size = size_match.group(1)

            if not title:
                continue

            info_url = guid or link or "https://torrentgalaxy.info"

            results.append({
                "name": title,
                "size": size,
                "seeders": seeders,
                "leechers": leechers,
                "magnet": magnet,
                "torrent": torrent_url,
                "url": info_url,
            })

    except Exception as e:
        log.warning("TorrentGalaxy search error: %s", e)

    return results
