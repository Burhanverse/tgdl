from __future__ import annotations

import html
import logging
import urllib.parse
from secrets import token_urlsafe
from typing import Any, Dict, List

from telegraph.aio import Telegraph

log = logging.getLogger(__name__)


class TelegraphHelper:
    """Helper to create minimal, modern Telegraph pages for search results using rich HTML tags."""

    def __init__(self, author_name: str = "TGDL Bot", author_url: str = "https://github.com/Burhanverse/tgdl") -> None:
        self.author_name = author_name
        self.author_url = author_url

    async def generate_telegraph_page(self, results: List[Dict[str, Any]], query: str, site: str) -> str | None:
        """Formats search results into a modern, minimal HTML layout and publishes to Telegraph."""
        if not results:
            return None

        safe_query = html.escape(query)
        safe_site = html.escape(site.capitalize())

        telegraph_content = []
        msg = f"<h3>Torrent Search Results: <code>{safe_query}</code></h3>"
        msg += f"<blockquote><b>Source Indexer:</b> {safe_site} &nbsp;•&nbsp; <b>Total Results:</b> {len(results)}</blockquote><hr>"

        for idx, result in enumerate(results, start=1):
            name = html.escape(str(result.get("name") or result.get("title") or "Unknown"))
            size = html.escape(str(result.get("size") or "N/A"))
            seeders = result.get("seeders", 0)
            leechers = result.get("leechers", 0)
            torrent_link = result.get("torrent") or result.get("url") or "#"
            magnet_link = result.get("magnet")

            item_html = f"<h4>{idx}. <a href='{torrent_link}'>{name}</a></h4>"
            item_html += f"<p><b>Size:</b> <code>{size}</code> &nbsp;•&nbsp; <b>Seeders:</b> {seeders} &nbsp;•&nbsp; <b>Leechers:</b> {leechers}</p>"

            links_html = []
            if magnet_link:
                quoted_mag = urllib.parse.quote(magnet_link)
                links_html.append(f"<a href='http://t.me/share/url?url={quoted_mag}'>Share Magnet to Telegram</a>")
            if torrent_link and torrent_link != "#" and not torrent_link.startswith("magnet:"):
                links_html.append(f"<a href='{torrent_link}'>Direct Link</a>")

            if links_html:
                item_html += f"<blockquote>{' &nbsp;•&nbsp; '.join(links_html)}</blockquote>"

            item_html += "<hr>"

            if len((msg + item_html).encode("utf-8")) > 38000:
                telegraph_content.append(msg)
                msg = ""

            msg += item_html

            if idx >= 300:  # Telegraph limit cap
                break

        if msg:
            telegraph_content.append(msg)

        for domain in ["graph.org", "telegra.ph"]:
            try:
                t = Telegraph(domain=domain)
                await t.create_account(
                    short_name=token_urlsafe(8),
                    author_name=self.author_name,
                    author_url=self.author_url,
                )
                paths = []
                for content in telegraph_content:
                    res = await t.create_page(
                        title=f"Torrent Search - {query[:25]}",
                        html_content=content,
                        author_name=self.author_name,
                        author_url=self.author_url,
                    )
                    paths.append(res["path"])

                if paths:
                    return f"https://{domain}/{paths[0]}"
            except Exception as e:
                log.warning("Failed to publish Telegraph page on %s: %s", domain, e)

        return None


telegraph_helper = TelegraphHelper()
