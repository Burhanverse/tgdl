from __future__ import annotations

import asyncio
import logging
import urllib.parse
from pathlib import Path
from typing import List, Optional

import aiohttp

from ...config import settings

log = logging.getLogger(__name__)

# Primary sources from XIU2/TrackersListCollection (updated daily)
XIU2_BEST_URL = "https://raw.githubusercontent.com/XIU2/TrackersListCollection/master/best.txt"
XIU2_ALL_URL = "https://raw.githubusercontent.com/XIU2/TrackersListCollection/master/all.txt"

# CDN / Secondary Mirrors
JSDELIVR_BEST_URL = "https://fastly.jsdelivr.net/gh/XIU2/TrackersListCollection/best.txt"
JSDELIVR_ALL_URL = "https://fastly.jsdelivr.net/gh/XIU2/TrackersListCollection/all.txt"
NGOSANG_BEST_URL = "https://raw.githubusercontent.com/ngosang/trackerslist/master/trackers_best.txt"

CACHE_FILE = settings.data_dir / "trackers_cache.txt"

# High quality fallback list in case network fetch fails completely
DEFAULT_TRACKERS: List[str] = [
    "http://1337.abcvg.info:80/announce",
    "http://bt1.archive.org:6969/announce",
    "http://bt2.archive.org:6969/announce",
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.stealth.si:80/announce",
    "udp://tracker.coppersurfer.tk:6969/announce",
    "udp://tracker.openbittorrent.com:6969/announce",
    "udp://tracker.internetwarriors.net:1337/announce",
    "udp://exodus.desync.com:6969/announce",
    "udp://open.demonii.com:1337/announce",
    "udp://tracker.cyberia.is:6969/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://retracker.lanta-net.ru:2710/announce",
    "udp://tracker.tiny-vps.com:6969/announce",
    "udp://valkyrie.info:6969/announce",
    "udp://ipv4.tracker.harry.lu:80/announce",
    "http://tracker.gbitt.info:80/announce",
    "http://tracker.ipv6tracker.ru:80/announce",
    "udp://tracker.dump.cl:6969/announce",
    "udp://tracker.dler.org:6969/announce",
]

_CACHED_TRACKERS: List[str] = []


def load_cached_trackers() -> List[str]:
    """Loads trackers from local cache file or returns DEFAULT_TRACKERS."""
    global _CACHED_TRACKERS
    if _CACHED_TRACKERS:
        return _CACHED_TRACKERS

    try:
        if CACHE_FILE.exists():
            content = CACHE_FILE.read_text(encoding="utf-8")
            lines = [line.strip() for line in content.splitlines() if line.strip() and not line.startswith("#")]
            if lines:
                _CACHED_TRACKERS = lines
                return _CACHED_TRACKERS
    except Exception as e:
        log.warning("Failed to read local trackers cache: %s", e)

    _CACHED_TRACKERS = list(DEFAULT_TRACKERS)
    return _CACHED_TRACKERS


async def fetch_latest_trackers() -> List[str]:
    """Fetches the latest daily trackers from XIU2/TrackersListCollection."""
    global _CACHED_TRACKERS
    fetched: set[str] = set()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    sources = [
        XIU2_BEST_URL,
        XIU2_ALL_URL,
        JSDELIVR_BEST_URL,
        JSDELIVR_ALL_URL,
        NGOSANG_BEST_URL,
    ]

    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            for url in sources:
                try:
                    async with session.get(url, timeout=8) as resp:
                        if resp.status == 200:
                            text = await resp.text()
                            for line in text.splitlines():
                                line = line.strip()
                                if line and not line.startswith("#"):
                                    fetched.add(line)
                except Exception as req_err:
                    log.warning("Failed fetching tracker list from %s: %s", url, req_err)

        if fetched:
            trackers_list = sorted(list(fetched))
            _CACHED_TRACKERS = trackers_list
            try:
                CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
                CACHE_FILE.write_text("\n".join(trackers_list), encoding="utf-8")
                log.info("Successfully updated %d trackers from XIU2/TrackersListCollection", len(trackers_list))
            except Exception as w_err:
                log.warning("Failed writing trackers cache file: %s", w_err)
            return trackers_list
    except Exception as e:
        log.warning("Error during trackers update from XIU2/TrackersListCollection: %s", e)

    return load_cached_trackers()


def get_trackers() -> List[str]:
    """Returns currently loaded trackers."""
    return load_cached_trackers()


def get_tracker_string() -> str:
    """Returns a comma-separated string of trackers formatted for aria2c --bt-tracker."""
    trackers = get_trackers()
    return ",".join(trackers)


def add_trackers_to_magnet(magnet_url: str, extra_trackers: Optional[List[str]] = None) -> str:
    """Appends live trackers to a magnet URI string."""
    if not magnet_url.startswith("magnet:"):
        return magnet_url

    trackers_to_add = extra_trackers if extra_trackers is not None else get_trackers()
    if not trackers_to_add:
        return magnet_url

    try:
        parsed = urllib.parse.urlparse(magnet_url)
        params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        existing_trackers = set(params.get("tr", []))

        new_tr_list = list(params.get("tr", []))
        for tr in trackers_to_add:
            if tr not in existing_trackers:
                new_tr_list.append(tr)
                existing_trackers.add(tr)

        params["tr"] = new_tr_list

        query_parts = []
        for k, vals in params.items():
            for v in vals:
                query_parts.append(f"{k}={urllib.parse.quote(v, safe=':/~_.-|()')}")

        new_query = "&".join(query_parts)
        return urllib.parse.urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment
        ))
    except Exception as e:
        log.warning("Failed to append trackers to magnet link: %s", e)
        return magnet_url
