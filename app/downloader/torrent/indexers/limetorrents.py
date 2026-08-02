"""
WARNING: This module relies on HTML scraping for LimeTorrents.
HTML web scraping is inherently fragile and has no stability guarantees.
Site layout changes, Cloudflare protection, or domain shifts may break this indexer at any time without notice.
Use at your own risk. Opt-in via configuration only.
"""

from __future__ import annotations

import logging
import urllib.parse
from html.parser import HTMLParser
from typing import Any

import aiohttp

log = logging.getLogger(__name__)


class _LimeTorrentsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, Any]] = []
        self._in_table = False
        self._in_tr = False
        self._in_td = False
        self._current_row_text: list[str] = []
        self._current_links: list[tuple[str, str]] = []
        self._current_a_href: str | None = None
        self._current_a_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = dict(attrs)
        if tag == "table":
            classes = attr_dict.get("class", "") or ""
            if "table2" in classes or "table" in classes:
                self._in_table = True
        elif tag == "tr" and self._in_table:
            self._in_tr = True
            self._current_row_text = []
            self._current_links = []
        elif tag == "td" and self._in_tr:
            self._in_td = True
        elif tag == "a" and self._in_tr:
            self._current_a_href = attr_dict.get("href")
            self._current_a_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._current_a_href is not None:
            text = "".join(self._current_a_text).strip()
            if text and self._current_a_href:
                self._current_links.append((self._current_a_href, text))
            self._current_a_href = None
            self._current_a_text = []
        elif tag == "td":
            self._in_td = False
        elif tag == "tr" and self._in_tr:
            self._in_tr = False
            self._process_row()

    def handle_data(self, data: str) -> None:
        if self._current_a_href is not None:
            self._current_a_text.append(data)
        elif self._in_td:
            cleaned = data.strip()
            if cleaned:
                self._current_row_text.append(cleaned)

    def _process_row(self) -> None:
        title_link = None
        for href, text in self._current_links:
            if "-torrent-" in href or ("/" in href and len(text) > 3 and not href.startswith("/search/")):
                title_link = (href, text)
                break

        if not title_link:
            return

        href, name = title_link
        url = f"https://www.limetorrents.lol{href}" if href.startswith("/") else href

        size = "N/A"
        nums = []
        for token in self._current_row_text:
            if any(unit in token for unit in ["B", "KB", "MB", "GB", "TB"]):
                size = token
            elif token.replace(",", "").isdigit():
                nums.append(int(token.replace(",", "")))

        seeders = nums[0] if len(nums) >= 1 else 0
        leechers = nums[1] if len(nums) >= 2 else 0

        self.results.append({
            "name": name,
            "size": size,
            "seeders": seeders,
            "leechers": leechers,
            "magnet": None,
            "url": url,
        })


async def search(query: str, limit: int) -> list[dict[str, Any]]:
    """HTML-scraped search for LimeTorrents (unstable fallback)."""
    encoded_query = urllib.parse.quote(query)
    url = f"https://www.limetorrents.lol/search/all/{encoded_query}/"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status != 200:
                    log.warning("LimeTorrents search returned HTTP status %s", resp.status)
                    return []
                html_content = await resp.text()

        parser = _LimeTorrentsParser()
        parser.feed(html_content)
        return parser.results[:limit]
    except Exception as e:
        log.warning("LimeTorrents search error: %s", e)
        return []
