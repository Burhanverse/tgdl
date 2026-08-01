from __future__ import annotations

import time

import pytest

from app.pacing import DownloadThrottler, parse_speed_limit


def test_parse_speed_limit():
    assert parse_speed_limit("20M") == 20 * 1024 * 1024
    assert parse_speed_limit("500K") == 500 * 1024
    assert parse_speed_limit("1.5M") == int(1.5 * 1024 * 1024)
    assert parse_speed_limit("1024") == 1024
    assert parse_speed_limit(512000) == 512000
    assert parse_speed_limit(None) is None
    assert parse_speed_limit("") is None
    assert parse_speed_limit("none") is None
    assert parse_speed_limit("0") is None
    assert parse_speed_limit("unlimited") is None


@pytest.mark.asyncio
async def test_download_throttler_async():
    # Rate: 100,000 bytes/sec
    rate = 100_000
    throttler = DownloadThrottler(rate)

    start = time.time()
    # Initial bucket starts with rate tokens (100,000)
    # Consuming 200,000 bytes requires an additional 100,000 tokens => ~1.0 second sleep
    await throttler.consume(100_000)
    await throttler.consume(100_000)
    elapsed = time.time() - start

    assert elapsed >= 0.8  # Expect ~1.0s, allow tolerance for timer resolution


def test_download_throttler_sync():
    rate = 100_000
    throttler = DownloadThrottler(rate)

    start = time.time()
    throttler.consume_sync(100_000)
    throttler.consume_sync(100_000)
    elapsed = time.time() - start

    assert elapsed >= 0.8
