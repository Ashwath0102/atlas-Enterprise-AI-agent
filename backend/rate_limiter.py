"""
backend/rate_limiter.py
───────────────────────
Production-grade async rate limiter (RPM + RPD) with exponential backoff/jitter,
and a disk-based cache keyed by SHA-256(file_content + model + prompt).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import time
from pathlib import Path
from typing import Optional

from backend.config import settings


# ─────────────────────────────────────────────────────────────────────────────
# RateLimiter
# ─────────────────────────────────────────────────────────────────────────────

class RateLimiter:
    """Async rate limiter enforcing per-minute and per-day request caps.

    Usage::

        async with rate_limiter.acquire():
            response = await call_api(...)
    """

    def __init__(self, max_rpm: int, max_rpd: int) -> None:
        self.max_rpm = max_rpm
        self.max_rpd = max_rpd

        self._lock = asyncio.Lock()
        self._minute_timestamps: list[float] = []
        self._day_timestamps: list[float] = []

        # Backoff config
        self._backoff_base: float = 1.0       # seconds
        self._backoff_max: float = 60.0       # seconds
        self._jitter_factor: float = 0.30     # ±30 %

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    class _AcquireContext:
        """Returned by acquire(); used as an async context manager."""

        def __init__(self, limiter: "RateLimiter") -> None:
            self._limiter = limiter

        async def __aenter__(self) -> None:
            await self._limiter._wait_for_slot()

        async def __aexit__(self, *_: object) -> None:
            pass

    def acquire(self) -> "_AcquireContext":
        """Return an async context manager that blocks until a slot is free."""
        return self._AcquireContext(self)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _wait_for_slot(self) -> None:
        attempt = 0
        while True:
            async with self._lock:
                now = time.monotonic()
                self._purge_old(now)

                rpm_ok = len(self._minute_timestamps) < self.max_rpm
                rpd_ok = len(self._day_timestamps) < self.max_rpd

                if rpm_ok and rpd_ok:
                    self._minute_timestamps.append(now)
                    self._day_timestamps.append(now)
                    return

            # Not ready — back off with jitter
            delay = min(self._backoff_base * (2 ** attempt), self._backoff_max)
            jitter = delay * self._jitter_factor * (2 * random.random() - 1)
            sleep_for = max(0.1, delay + jitter)
            await asyncio.sleep(sleep_for)
            attempt += 1

    def _purge_old(self, now: float) -> None:
        """Remove timestamps outside the relevant windows."""
        one_minute_ago = now - 60.0
        one_day_ago = now - 86400.0
        self._minute_timestamps = [
            t for t in self._minute_timestamps if t > one_minute_ago
        ]
        self._day_timestamps = [
            t for t in self._day_timestamps if t > one_day_ago
        ]


# ─────────────────────────────────────────────────────────────────────────────
# CacheManager
# ─────────────────────────────────────────────────────────────────────────────

class CacheManager:
    """Simple disk-based JSON cache keyed by SHA-256 hashes.

    Cache files live in ``<cache_dir>/<key>.json``.
    """

    def __init__(self, cache_dir: str | Path = "cache") -> None:
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Key construction
    # ------------------------------------------------------------------

    @staticmethod
    def get_cache_key(file_path: str, model: str, prompt: str) -> str:
        """Return the SHA-256 hex digest of file_content + model + prompt.

        If *file_path* does not point to an existing file the path string
        itself is hashed instead (useful for in-memory or synthetic inputs).
        """
        hasher = hashlib.sha256()
        p = Path(file_path)
        if p.is_file():
            hasher.update(p.read_bytes())
        else:
            hasher.update(file_path.encode())
        hasher.update(model.encode())
        hasher.update(prompt.encode())
        return hasher.hexdigest()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def _path(self, key: str) -> Path:
        return self._cache_dir / f"{key}.json"

    def exists(self, key: str) -> bool:
        """Return True if a cache entry for *key* exists on disk."""
        return self._path(key).is_file()

    def get(self, key: str) -> Optional[dict]:
        """Read and return the cached dict, or None if not found."""
        path = self._path(key)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def set(self, key: str, value: dict) -> None:
        """Persist *value* as JSON under *key*."""
        self._path(key).write_text(
            json.dumps(value, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Module-level singletons
# ─────────────────────────────────────────────────────────────────────────────

rate_limiter = RateLimiter(
    max_rpm=settings.RATE_LIMIT_RPM,
    max_rpd=settings.RATE_LIMIT_RPD,
)

cache_manager = CacheManager(cache_dir=settings.CACHE_DIR)
