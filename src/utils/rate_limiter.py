"""Rate limiting utilities for API and scraping calls."""

from __future__ import annotations

import asyncio
from collections import defaultdict

from aiolimiter import AsyncLimiter


# Per-source rate limits (requests per minute)
DEFAULT_LIMITS: dict[str, tuple[int, int]] = {
    "linkedin": (5, 60),       # 5 requests per 60 seconds
    "indeed": (15, 60),        # 15 requests per 60 seconds
    "glassdoor": (10, 60),     # 10 requests per 60 seconds
    "greenhouse": (30, 60),    # 30 requests per 60 seconds
    "lever": (30, 60),         # 30 requests per 60 seconds
    "hn_hiring": (60, 60),     # 60 requests per 60 seconds (generous)
    "claude_api": (50, 60),    # 50 requests per 60 seconds
    "default": (10, 60),       # 10 requests per 60 seconds
}


class RateLimiterManager:
    """Manages per-source rate limiters."""

    def __init__(self, overrides: dict[str, tuple[int, int]] | None = None):
        self._limiters: dict[str, AsyncLimiter] = {}
        self._limits = {**DEFAULT_LIMITS, **(overrides or {})}

    def get(self, source: str) -> AsyncLimiter:
        if source not in self._limiters:
            max_rate, time_period = self._limits.get(
                source, self._limits["default"]
            )
            self._limiters[source] = AsyncLimiter(max_rate, time_period)
        return self._limiters[source]

    async def acquire(self, source: str) -> None:
        limiter = self.get(source)
        await limiter.acquire()


# Global instance
rate_limiters = RateLimiterManager()
