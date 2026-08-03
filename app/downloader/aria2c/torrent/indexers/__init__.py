from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from .apibay import search as apibay_search
from .nyaa import search as nyaa_search
from .torrents_csv import search as torrents_csv_search
from .yts import search as yts_search

log = logging.getLogger(__name__)

INDEXERS: dict[str, Callable[[str, int], Coroutine[Any, Any, list[dict[str, Any]]]]] = {
    "apibay": apibay_search,
    "torrents_csv": torrents_csv_search,
    "nyaa": nyaa_search,
    "yts": yts_search,
}


def extract_info_hash(magnet: str | None) -> str | None:
    """Extracts uppercase hex/b32 infohash from a magnet URI if present."""
    if not magnet or "urn:btih:" not in magnet.lower():
        return None
    try:
        lower_mag = magnet.lower()
        idx = lower_mag.find("urn:btih:")
        if idx != -1:
            raw_hash = magnet[idx + 9:].split("&")[0].strip()
            if raw_hash:
                return raw_hash.upper()
    except Exception:
        pass
    return None


def dedupe_key(item: dict[str, Any]) -> Any:
    """Returns deduplication key: magnet infohash if available, else (name.lower(), size)."""
    magnet = item.get("magnet")
    info_hash = extract_info_hash(magnet)
    if info_hash:
        return info_hash

    name = str(item.get("name") or "").strip().lower()
    size = str(item.get("size") or "").strip()
    return (name, size)


async def run_enabled_indexers(
    query: str, limit: int = 20, enabled_names: list[str] | None = None
) -> list[dict[str, Any]]:
    """Fires requested indexers concurrently, logs warnings on error, merges, dedupes, and sorts by seeders."""
    if not enabled_names:
        enabled_names = ["apibay", "torrents_csv", "nyaa", "yts"]

    selected_indexers: list[tuple[str, Callable[[str, int], Coroutine[Any, Any, list[dict[str, Any]]]]]] = []
    for name in enabled_names:
        norm_name = name.strip().lower()
        if norm_name in INDEXERS:
            selected_indexers.append((norm_name, INDEXERS[norm_name]))
        else:
            log.warning("Unknown torrent indexer requested: %s", name)

    if not selected_indexers:
        return []

    tasks = [func(query, limit) for _, func in selected_indexers]
    results_raw = await asyncio.gather(*tasks, return_exceptions=True)

    merged: list[dict[str, Any]] = []
    for (name, _), res in zip(selected_indexers, results_raw, strict=False):
        if isinstance(res, Exception):
            log.warning("Indexer '%s' raised an exception: %s", name, res)
        elif isinstance(res, list):
            merged.extend(res)

    # Deduplicate results
    seen: set[Any] = set()
    deduped: list[dict[str, Any]] = []
    for item in merged:
        key = dedupe_key(item)
        if key not in seen:
            seen.add(key)
            deduped.append(item)

    # Sort by seeders descending
    deduped.sort(key=lambda x: int(x.get("seeders", 0) or 0), reverse=True)

    return deduped[:limit]


__all__ = ["INDEXERS", "dedupe_key", "extract_info_hash", "run_enabled_indexers"]
