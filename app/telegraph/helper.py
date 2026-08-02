from __future__ import annotations

import html
import logging
import urllib.parse
from asyncio import sleep
from secrets import token_urlsafe
from typing import Any

from .client import Telegraph
from .parser import RetryAfterError

log = logging.getLogger(__name__)


class TelegraphHelper:
    """Helper to manage Telegraph accounts, page creation, flood-wait retries, and paginated HTML search results."""

    def __init__(
        self,
        author_name: str = "TGDL",
        author_url: str = "https://github.com/Burhanverse/tgdl",
        default_domain: str = "graph.org",
    ) -> None:
        self.author_name = author_name
        self.author_url = author_url
        self.default_domain = default_domain
        self._tokens: dict[str, str] = {}

    async def get_client(self, domain: str | None = None) -> Telegraph:
        """Gets or initializes a Telegraph client for a specific domain with a cached account token."""
        dom = domain or self.default_domain
        token = self._tokens.get(dom)
        client = Telegraph(access_token=token, domain=dom)
        if not token:
            try:
                res = await client.create_account(
                    short_name=token_urlsafe(8),
                    author_name=self.author_name,
                    author_url=self.author_url,
                )
                if isinstance(res, dict) and "access_token" in res:
                    self._tokens[dom] = res["access_token"]
            except Exception as exc:
                log.warning("Failed to create Telegraph account on domain %s: %s", dom, exc)
        return client

    async def create_page(
        self,
        title: str,
        content: str,
        domain: str | None = None,
    ) -> dict[str, Any]:
        """Creates a page with flood-wait auto-retry handling."""
        dom = domain or self.default_domain
        client = await self.get_client(dom)
        try:
            return await client.create_page(
                title=title,
                html_content=content,
                author_name=self.author_name,
                author_url=self.author_url,
            )
        except RetryAfterError as st:
            log.warning("Telegraph flood control reached for domain %s. Waiting %d seconds.", dom, st.retry_after)
            await sleep(st.retry_after)
            return await self.create_page(title, content, domain=dom)
        finally:
            await client.close()

    async def edit_page(
        self,
        path: str,
        title: str,
        content: str,
        domain: str | None = None,
    ) -> dict[str, Any]:
        """Edits a page with flood-wait auto-retry handling."""
        dom = domain or self.default_domain
        client = await self.get_client(dom)
        try:
            return await client.edit_page(
                path=path,
                title=title,
                html_content=content,
                author_name=self.author_name,
                author_url=self.author_url,
            )
        except RetryAfterError as st:
            log.warning("Telegraph flood control reached for domain %s. Waiting %d seconds.", dom, st.retry_after)
            await sleep(st.retry_after)
            return await self.edit_page(path, title, content, domain=dom)
        finally:
            await client.close()

    async def link_paginated_pages(
        self,
        paths: list[str],
        title: str,
        page_contents: list[str],
        domain: str | None = None,
    ) -> None:
        """Adds Prev and Next navigation links to multiple pages after initial creation."""
        dom = domain or self.default_domain
        num_pages = len(paths)
        if num_pages <= 1:
            return

        for idx, (path, content) in enumerate(zip(paths, page_contents)):
            nav_parts = []
            if idx > 0:
                prev_path = paths[idx - 1]
                nav_parts.append(f'<b><a href="https://{dom}/{prev_path}">‹ Prev</a></b>')
            if idx < num_pages - 1:
                next_path = paths[idx + 1]
                nav_parts.append(f'<b><a href="https://{dom}/{next_path}">Next ›</a></b>')

            if nav_parts:
                nav_bar = f"<hr><p align='center'>{' &nbsp;|&nbsp; '.join(nav_parts)}</p>"
                updated_content = content + nav_bar
                try:
                    await self.edit_page(path=path, title=title, content=updated_content, domain=dom)
                except Exception as exc:
                    log.warning("Failed to link navigation on page %s (%s): %s", path, dom, exc)

    async def generate_telegraph_page(
        self,
        results: list[dict[str, Any]],
        query: str,
        site: str,
    ) -> str | None:
        """Formats search results into modern HTML layout and publishes to Telegraph with domain fallback."""
        if not results:
            return None

        safe_query = html.escape(query)
        safe_site = html.escape(site.capitalize())

        telegraph_content: list[str] = []
        header = f"<h3>Torrent Search Results: <code>{safe_query}</code></h3>"
        header += f"<blockquote><b>Source Indexer:</b> {safe_site} &nbsp;•&nbsp; <b>Total Results:</b> {len(results)}</blockquote><hr>"
        current_msg = header

        for idx, result in enumerate(results, start=1):
            name = html.escape(str(result.get("name") or result.get("title") or "Unknown"))
            size = html.escape(str(result.get("size") or "N/A"))
            seeders = result.get("seeders", 0)
            leechers = result.get("leechers", 0)
            raw_torrent_link = str(result.get("torrent") or result.get("url") or "#")
            raw_magnet_link = str(result.get("magnet") or "")
            safe_torrent_link = html.escape(raw_torrent_link, quote=True)

            item_html = f"<h4>{idx}. <a href='{safe_torrent_link}'>{name}</a></h4>"
            item_html += f"<p><b>Size:</b> <code>{size}</code> &nbsp;•&nbsp; <b>Seeders:</b> {seeders} &nbsp;•&nbsp; <b>Leechers:</b> {leechers}</p>"

            links_html = []
            if raw_magnet_link:
                quoted_mag = html.escape(urllib.parse.quote(raw_magnet_link), quote=True)
                links_html.append(f"<a href='http://t.me/share/url?url={quoted_mag}'>Share Magnet to Telegram</a>")
            if raw_torrent_link and raw_torrent_link != "#" and not raw_torrent_link.startswith("magnet:"):
                links_html.append(f"<a href='{safe_torrent_link}'>Direct Link</a>")

            if links_html:
                item_html += f"<blockquote>{' &nbsp;•&nbsp; '.join(links_html)}</blockquote>"

            item_html += "<hr>"

            if len((current_msg + item_html).encode("utf-8")) > 38000:
                telegraph_content.append(current_msg)
                current_msg = header

            current_msg += item_html

            if idx >= 300:  # Telegraph max item limit
                break

        if current_msg and current_msg != header:
            telegraph_content.append(current_msg)

        if not telegraph_content:
            return None

        page_title = f"Torrent Search - {query[:25]}"

        # Domain fallback: Try graph.org, fallback to telegra.ph
        for domain in [self.default_domain, "telegra.ph"]:
            try:
                paths: list[str] = []
                for content in telegraph_content:
                    res = await self.create_page(title=page_title, content=content, domain=domain)
                    if res and "path" in res:
                        paths.append(res["path"])

                if paths:
                    if len(paths) > 1:
                        await self.link_paginated_pages(
                            paths=paths,
                            title=page_title,
                            page_contents=telegraph_content,
                            domain=domain,
                        )
                    return f"https://{domain}/{paths[0]}"
            except Exception as exc:
                log.warning("Failed to publish Telegraph page on %s: %s", domain, exc)

        return None


telegraph_helper = TelegraphHelper()
