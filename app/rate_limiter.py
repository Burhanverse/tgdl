from __future__ import annotations

import asyncio
import logging
import random
import re
import time

log = logging.getLogger(__name__)

RATE_LIMIT_PATTERNS = re.compile(
    r"\b(429|403|too many requests|rate.?limit|temporarily blocked|forbidden|quota exceeded|retry after|cloudflare|turnstile)\b",
    re.IGNORECASE,
)


def looks_rate_limited(text: str) -> bool:
    """Check if an error log or output string indicates rate limiting."""
    if not text:
        return False
    return bool(RATE_LIMIT_PATTERNS.search(text))


class Backoff:
    """Exponential backoff with full jitter according to AWS/best practice guidelines."""

    def __init__(
        self,
        base_s: float = 1.0,
        multiplier: float = 2.0,
        max_attempts: int = 5,
        max_delay_s: float = 60.0,
        jitter: bool = True,
    ):
        self.base_s = base_s
        self.multiplier = multiplier
        self.max_attempts = max_attempts
        self.max_delay_s = max_delay_s
        self.jitter = jitter
        self.attempt = 0

    def reset(self) -> None:
        self.attempt = 0

    def next_delay(self) -> float:
        calculated = self.base_s * (self.multiplier**self.attempt)
        delay = min(self.max_delay_s, calculated)
        if self.jitter:
            delay = random.uniform(0.0, delay)
        self.attempt += 1
        return delay

    @property
    def exhausted(self) -> bool:
        return self.attempt >= self.max_attempts


SWEEP_INTERVAL_SECONDS: float = 3600.0
STALENESS_THRESHOLD_SECONDS: float = 86400.0


class TelegramRateLimiter:
    """Async Rate Limiter enforcing Telegram API limits:

    - Global limit: max 30 ops/sec across all chats.
    - Per-chat limit: minimum interval between calls (e.g. 1.0s).
    - FloodWait Cooldown: dynamic penalty tracking on FloodWait.
    """

    def __init__(
        self,
        global_rate_limit: float = 30.0,  # max requests per second globally
        per_chat_interval: float = 2.0,    # min seconds between calls in same chat
    ):
        self.global_rate_limit = global_rate_limit
        self.per_chat_interval = per_chat_interval
        self.per_upload_interval = 3.0

        self._global_lock = asyncio.Lock()
        self._global_last_call = 0.0

        self._chat_locks: dict[int, asyncio.Lock] = {}
        self._chat_last_call: dict[int, float] = {}
        self._chat_last_upload: dict[int, float] = {}
        self._chat_floodwait_until: dict[int, float] = {}
        self._global_floodwait_until: float = 0.0

    def _get_chat_lock(self, chat_id: int) -> asyncio.Lock:
        if chat_id not in self._chat_locks:
            self._chat_locks[chat_id] = asyncio.Lock()
        return self._chat_locks[chat_id]

    async def acquire(self, chat_id: int | None = None) -> None:
        """Paces execution according to Telegram rate limits."""
        now = time.time()

        # Check global FloodWait pause
        if now < self._global_floodwait_until:
            wait_s = self._global_floodwait_until - now
            log.debug("Global FloodWait pause active, waiting %.2fs", wait_s)
            await asyncio.sleep(wait_s)
            now = time.time()

        # Check per-chat FloodWait pause
        if chat_id is not None:
            flood_until = self._chat_floodwait_until.get(chat_id, 0.0)
            if now < flood_until:
                wait_s = flood_until - now
                log.debug("Chat %s FloodWait pause active, waiting %.2fs", chat_id, wait_s)
                await asyncio.sleep(wait_s)
                now = time.time()

        # Enforce global pacing (1 / 30 = ~0.033s between calls)
        async with self._global_lock:
            min_global_interval = 1.0 / self.global_rate_limit
            elapsed = time.time() - self._global_last_call
            if elapsed < min_global_interval:
                await asyncio.sleep(min_global_interval - elapsed)
            self._global_last_call = time.time()

        # Enforce per-chat pacing (min 1.0s between calls in same chat)
        if chat_id is not None:
            chat_lock = self._get_chat_lock(chat_id)
            async with chat_lock:
                last_call = self._chat_last_call.get(chat_id, 0.0)
                elapsed = time.time() - last_call
                if elapsed < self.per_chat_interval:
                    await asyncio.sleep(self.per_chat_interval - elapsed)
                self._chat_last_call[chat_id] = time.time()

    async def acquire_upload(self, chat_id: int | None = None) -> None:
        """Paces execution specifically for Telegram file & media uploads (3.0s min gap)."""
        await self.acquire(chat_id)
        if chat_id is not None:
            chat_lock = self._get_chat_lock(chat_id)
            async with chat_lock:
                last_upload = self._chat_last_upload.get(chat_id, 0.0)
                elapsed = time.time() - last_upload
                if elapsed < self.per_upload_interval:
                    await asyncio.sleep(self.per_upload_interval - elapsed)
                self._chat_last_upload[chat_id] = time.time()

    def notify_floodwait(self, seconds: int, chat_id: int | None = None) -> None:
        """Register a FloodWait penalty so subsequent calls wait out the penalty."""
        until = time.time() + seconds + 1.0
        if chat_id is not None:
            self._chat_floodwait_until[chat_id] = max(self._chat_floodwait_until.get(chat_id, 0.0), until)
            log.warning("Registered FloodWait of %ss for chat %s", seconds, chat_id)
        else:
            self._global_floodwait_until = max(self._global_floodwait_until, until)
            log.warning("Registered global FloodWait of %ss", seconds)

    def cleanup_stale_chats(
        self,
        active_chat_ids: set[int] | None = None,
        staleness_threshold: float = STALENESS_THRESHOLD_SECONDS,
    ) -> int:
        """Evict pacing state for chats that haven't been active for longer than staleness_threshold and have no active jobs."""
        if active_chat_ids is None:
            active_chat_ids = set()

        now = time.time()
        all_chat_ids = (
            set(self._chat_locks.keys())
            | set(self._chat_last_call.keys())
            | set(self._chat_last_upload.keys())
            | set(self._chat_floodwait_until.keys())
        )

        evicted_count = 0
        for chat_id in all_chat_ids:
            if chat_id in active_chat_ids:
                continue

            last_call = self._chat_last_call.get(chat_id, 0.0)
            last_upload = self._chat_last_upload.get(chat_id, 0.0)
            flood_until = self._chat_floodwait_until.get(chat_id, 0.0)

            most_recent = max(last_call, last_upload, flood_until)
            if now - most_recent > staleness_threshold:
                lock = self._chat_locks.get(chat_id)
                if lock and lock.locked():
                    continue

                self._chat_locks.pop(chat_id, None)
                self._chat_last_call.pop(chat_id, None)
                self._chat_last_upload.pop(chat_id, None)
                self._chat_floodwait_until.pop(chat_id, None)
                evicted_count += 1

        if evicted_count > 0:
            log.info("Cleaned up %d stale chat entries from TelegramRateLimiter", evicted_count)
        return evicted_count

    async def start_periodic_sweep(
        self,
        sweep_interval: float = SWEEP_INTERVAL_SECONDS,
        staleness_threshold: float = STALENESS_THRESHOLD_SECONDS,
    ) -> None:
        """Background loop running periodic sweep of stale chat rate-limiter states."""
        while True:
            await asyncio.sleep(sweep_interval)
            try:
                from .manager.core import queue_manager
                active_chat_ids = (
                    {js.job.chat_id for js in queue_manager.jobs.values()}
                    if queue_manager
                    else set()
                )
            except Exception:
                active_chat_ids = set()

            self.cleanup_stale_chats(
                active_chat_ids=active_chat_ids,
                staleness_threshold=staleness_threshold,
            )


# Global rate limiter instance for Telegram API calls
telegram_limiter = TelegramRateLimiter()
