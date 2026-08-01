from __future__ import annotations

import asyncio
import re
import time

_SPEED_PATTERN = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([a-zA-Z]*)\s*$", re.IGNORECASE)

_UNITS = {
    "": 1,
    "b": 1,
    "k": 1024,
    "kb": 1024,
    "kib": 1024,
    "m": 1024 * 1024,
    "mb": 1024 * 1024,
    "mib": 1024 * 1024,
    "g": 1024 * 1024 * 1024,
    "gb": 1024 * 1024 * 1024,
    "gib": 1024 * 1024 * 1024,
}


def parse_speed_limit(limit_str: str | float | None) -> int | None:
    """Parse speed limit strings (e.g. '20M', '500K', '1.5M', '1024') or numbers into bytes/sec.

    Returns None for unlimited/falsy/invalid inputs.
    """
    if limit_str is None:
        return None

    if isinstance(limit_str, (int, float)):
        return int(limit_str) if limit_str > 0 else None

    cleaned = str(limit_str).strip().lower()
    if not cleaned or cleaned in ("none", "0", "unlimited", "off", "false"):
        return None

    match = _SPEED_PATTERN.match(cleaned)
    if not match:
        return None

    num_str, unit_str = match.groups()
    try:
        val = float(num_str)
        multiplier = _UNITS.get(unit_str, 1)
        res = int(val * multiplier)
        return res if res > 0 else None
    except (ValueError, TypeError):
        return None


class DownloadThrottler:
    """Token-bucket rate limiter for chunked streams (supports async and sync consumption)."""

    def __init__(self, rate_bytes_per_sec: float | str | None):
        if isinstance(rate_bytes_per_sec, str):
            self.rate_bytes_per_sec = parse_speed_limit(rate_bytes_per_sec)
        else:
            self.rate_bytes_per_sec = (
                int(rate_bytes_per_sec) if rate_bytes_per_sec and rate_bytes_per_sec > 0 else None
            )

        self.last_check = time.time()
        self.tokens = float(self.rate_bytes_per_sec) if self.rate_bytes_per_sec else 0.0

    @classmethod
    def from_settings(cls) -> DownloadThrottler:
        from ..config import settings

        return cls(settings.global_download_speed_limit)

    async def consume(self, chunk_size: int) -> None:
        if not self.rate_bytes_per_sec or chunk_size <= 0:
            return

        now = time.time()
        elapsed = now - self.last_check
        self.last_check = now

        rate = float(self.rate_bytes_per_sec)
        self.tokens = min(rate, self.tokens + elapsed * rate)
        self.tokens -= chunk_size

        if self.tokens < 0:
            wait_time = abs(self.tokens) / rate
            await asyncio.sleep(wait_time)
            self.last_check = time.time()
            self.tokens = 0.0

    def consume_sync(self, chunk_size: int) -> None:
        if not self.rate_bytes_per_sec or chunk_size <= 0:
            return

        now = time.time()
        elapsed = now - self.last_check
        self.last_check = now

        rate = float(self.rate_bytes_per_sec)
        self.tokens = min(rate, self.tokens + elapsed * rate)
        self.tokens -= chunk_size

        if self.tokens < 0:
            wait_time = abs(self.tokens) / rate
            time.sleep(wait_time)
            self.last_check = time.time()
            self.tokens = 0.0
