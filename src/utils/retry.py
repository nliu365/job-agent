"""Retry utilities with exponential backoff."""

from __future__ import annotations

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# Retry decorator for HTTP calls
http_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.ConnectTimeout, httpx.ReadTimeout)),
    reraise=True,
)


async def fetch_with_retry(
    client: httpx.AsyncClient,
    url: str,
    **kwargs,
) -> httpx.Response:
    """Fetch a URL with automatic retry on failure and rate limit handling."""

    @http_retry
    async def _fetch():
        response = await client.get(url, **kwargs)
        if response.status_code == 429:
            import asyncio

            retry_after = int(response.headers.get("Retry-After", "60"))
            await asyncio.sleep(retry_after)
            response.raise_for_status()
        response.raise_for_status()
        return response

    return await _fetch()
