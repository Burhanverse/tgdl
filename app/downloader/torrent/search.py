from __future__ import annotations

import asyncio
import html
import logging
import urllib.parse
from typing import Any

import aiohttp

from ...config import settings

log = logging.getLogger(__name__)

SITES: dict[str, str] | None = None
TELEGRAPH_LIMIT = 300


def format_bytes(size: float) -> str:
    """Formats bytes into human readable string."""
    try:
        size = float(size)
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if abs(size) < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} PB"
    except Exception:
        return "N/A"


async def search_prowlarr(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Performs torrent search using Prowlarr API via prowlarr-py wrapper."""
    if not settings.prowlarr_url or not settings.prowlarr_api_key:
        return []

    results: list[dict[str, Any]] = []

    def _prowlarr_sync() -> list[dict[str, Any]]:
        try:
            import prowlarr
            config = prowlarr.Configuration(host=settings.prowlarr_url.rstrip("/"))
            config.api_key["X-Api-Key"] = settings.prowlarr_api_key

            with prowlarr.ApiClient(config) as api_client:
                search_api = prowlarr.SearchApi(api_client)
                raw_releases = search_api.list_search(query=query)

                items = []
                if raw_releases:
                    for r in raw_releases[:limit]:
                        title = getattr(r, "title", None) or "Unknown"
                        size = format_bytes(getattr(r, "size", 0) or 0)
                        seeders = int(getattr(r, "seeders", 0) or 0)
                        leechers = int(getattr(r, "leechers", 0) or 0)
                        download_url = getattr(r, "download_url", None)
                        magnet_url = getattr(r, "magnet_url", None)
                        info_url = getattr(r, "info_url", None)

                        items.append({
                            "name": title,
                            "size": size,
                            "seeders": seeders,
                            "leechers": leechers,
                            "magnet": magnet_url,
                            "torrent": download_url if download_url and not download_url.startswith("magnet:") else None,
                            "url": info_url or download_url or "#",
                        })
                return items
        except Exception as err:
            log.warning("Prowlarr search execution error: %s", err)
            return []

    try:
        results = await asyncio.to_thread(_prowlarr_sync)
    except Exception as e:
        log.warning("Prowlarr search thread error: %s", e)

    return results


async def search_apibay_and_csv(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Free public fallback torrent search using Apibay (PirateBay) and Torrents-CSV."""
    results: list[dict[str, Any]] = []
    encoded_query = urllib.parse.quote(query)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    async with aiohttp.ClientSession(headers=headers) as session:
        # 1. Query Apibay (PirateBay)
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
                            magnet = f"magnet:?xt=urn:btih:{info_hash}&dn={urllib.parse.quote(name)}" if info_hash else None

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

        # 2. Query Torrents-CSV if needed
        if len(results) < limit:
            try:
                url = f"https://torrents-csv.com/service/search?q={encoded_query}"
                async with session.get(url, timeout=8) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        torrents = data.get("torrents", [])
                        for item in torrents[:limit - len(results)]:
                            name = item.get("name")
                            if not name:
                                continue
                            info_hash = item.get("infohash")
                            size = format_bytes(item.get("size", 0))
                            seeders = int(item.get("seeders", 0))
                            leechers = int(item.get("leechers", 0))
                            magnet = f"magnet:?xt=urn:btih:{info_hash}&dn={urllib.parse.quote(name)}" if info_hash else None

                            results.append({
                                "name": name,
                                "size": size,
                                "seeders": seeders,
                                "leechers": leechers,
                                "magnet": magnet,
                                "url": "https://torrents-csv.com",
                            })
            except Exception as e:
                log.warning("Torrents-CSV search error: %s", e)

    return results


async def initiate_search_tools() -> None:
    """Initializes Prowlarr and external search API sites if configured."""
    global SITES
    if SITES is None:
        SITES = {}

    if settings.prowlarr_url and settings.prowlarr_api_key:
        SITES["prowlarr"] = "Prowlarr"

    if settings.search_api_link:
        try:
            url = f"{settings.search_api_link.rstrip('/')}/api/v1/sites"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        supported = data.get("supported_sites", [])
                        for site in supported:
                            SITES[str(site)] = str(site).capitalize()
                        SITES["all"] = "All API Sites"
                        log.info("Loaded %d search sites from SEARCH_API_LINK", len(supported))
                    else:
                        log.warning("SEARCH_API_LINK returned status code %s", resp.status)
        except Exception as e:
            log.warning("Failed to fetch sites from SEARCH_API_LINK: %s", e)

    if not SITES:
        SITES = {"public": "Public Indexers"}


async def search_torrents(key: str, site: str = "all", method: str = "apisearch") -> list[dict[str, Any]]:
    """Performs a torrent search using Prowlarr, Search API, or public fallbacks."""
    results: list[dict[str, Any]] = []
    limit = settings.search_limit or 20

    # 1. Try Prowlarr if configured or specifically selected
    if site == "prowlarr" or (settings.prowlarr_url and settings.prowlarr_api_key and method != "api"):
        results = await search_prowlarr(key, limit=limit)
        if results:
            return results

    # 2. Try Search API
    if method.startswith("api") and settings.search_api_link:
        base = settings.search_api_link.rstrip("/")
        encoded_key = urllib.parse.quote(key)

        if method == "apisearch":
            if site in ["all", "prowlarr", "public"]:
                api_url = f"{base}/api/v1/all/search?query={encoded_key}&limit={limit}"
            else:
                api_url = f"{base}/api/v1/search?site={site}&query={encoded_key}&limit={limit}"
        elif method == "apitrend":
            api_url = f"{base}/api/v1/all/trending?limit={limit}"
        elif method == "apirecent":
            api_url = f"{base}/api/v1/all/recent?limit={limit}"
        else:
            api_url = f"{base}/api/v1/all/search?query={encoded_key}&limit={limit}"

        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=15) as resp:
                if resp.status == 200:
                    raw_results = await resp.json()
                    if isinstance(raw_results, list):
                        results = raw_results
                    elif isinstance(raw_results, dict) and "data" in raw_results:
                        results = raw_results["data"]
                else:
                    log.error("API search failed with status %s for URL %s", resp.status, api_url)

    # 3. Public fallback if no results yet
    if not results:
        results = await search_apibay_and_csv(key, limit=limit)

    return results


def format_search_results_html(results: list[dict[str, Any]], query: str, site: str) -> str:
    """Formats search results into clean HTML for Telegram messages."""
    if not results:
        return f"<b>No torrent results found</b> for <i>{html.escape(query)}</i>."

    msg = f"<b>Search Results for:</b> <code>{html.escape(query)}</code>\n"
    msg += f"<b>Source:</b> {html.escape(site.capitalize())} | <b>Total:</b> {len(results)}\n\n"

    for idx, item in enumerate(results[:15], start=1):
        name = item.get("name") or item.get("title") or "Unknown"
        size = item.get("size") or "N/A"
        seeders = item.get("seeders", 0)
        leechers = item.get("leechers", 0)
        torrent_link = item.get("torrent") or item.get("url")
        magnet_link = item.get("magnet")

        msg += f"<b>{idx}. {html.escape(str(name))}</b>\n"
        msg += f"├ <b>Size:</b> {size} | <b>S:</b> {seeders} | <b>L:</b> {leechers}\n"

        links = []
        if magnet_link:
            encoded_mag = urllib.parse.quote(magnet_link)
            links.append(f"<a href='http://t.me/share/url?url={encoded_mag}'>Share Magnet</a>")
        if torrent_link and not torrent_link.startswith("magnet:"):
            links.append(f"<a href='{torrent_link}'>Direct Link</a>")

        if links:
            msg += f"└ {' | '.join(links)}\n\n"
        else:
            msg += "\n"

    return msg
