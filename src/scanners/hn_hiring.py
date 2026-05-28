"""Hacker News Who's Hiring thread scanner."""

from __future__ import annotations

import asyncio
import html
import re
from datetime import datetime

import httpx
import structlog

from src.config import AppConfig
from src.models import Job, JobSource
from src.scanners.base import BaseScanner
from src.utils.retry import fetch_with_retry

log = structlog.get_logger()

HN_API = "https://hacker-news.firebaseio.com/v0"
ALGOLIA_API = "https://hn.algolia.com/api/v1"


class HNHiringScanner(BaseScanner):
    def __init__(self, config: AppConfig):
        super().__init__(config)

    @property
    def source(self) -> JobSource:
        return JobSource.HN_HIRING

    async def scan(self) -> list[Job]:
        async with httpx.AsyncClient(timeout=30) as client:
            thread_id = await self._find_latest_thread(client)
            if not thread_id:
                log.warning("hn_no_thread_found")
                return []

            log.info("hn_thread_found", thread_id=thread_id)
            thread = await self._fetch_item(client, thread_id)
            comment_ids = thread.get("kids", [])

            jobs: list[Job] = []
            # Process comments in batches to avoid overwhelming the API
            batch_size = 20
            for i in range(0, len(comment_ids), batch_size):
                batch = comment_ids[i : i + batch_size]
                tasks = [self._process_comment(client, cid) for cid in batch]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for result in results:
                    if isinstance(result, Job):
                        jobs.append(result)
                await self._rate_limit_pause()

            log.info("hn_scan_complete", total_comments=len(comment_ids), jobs_found=len(jobs))
            return jobs

    async def _find_latest_thread(self, client: httpx.AsyncClient) -> int | None:
        """Find the latest 'Who is hiring?' thread via Algolia."""
        now = datetime.utcnow()
        # Search for threads from the current month
        first_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        timestamp = int(first_of_month.timestamp())

        url = f"{ALGOLIA_API}/search"
        params = {
            "query": "Ask HN: Who is hiring?",
            "tags": "ask_hn",
            "numericFilters": f"created_at_i>{timestamp}",
        }

        try:
            response = await fetch_with_retry(client, url, params=params)
            data = response.json()
            hits = data.get("hits", [])

            for hit in hits:
                title = hit.get("title", "")
                if "who is hiring" in title.lower() and hit.get("author") == "whoishiring":
                    return int(hit["objectID"])

            # Fallback: try previous month
            if not hits:
                if now.month == 1:
                    prev_month = now.replace(year=now.year - 1, month=12, day=1)
                else:
                    prev_month = now.replace(month=now.month - 1, day=1)
                params["numericFilters"] = f"created_at_i>{int(prev_month.timestamp())}"
                response = await fetch_with_retry(client, url, params=params)
                data = response.json()
                for hit in data.get("hits", []):
                    title = hit.get("title", "")
                    if "who is hiring" in title.lower():
                        return int(hit["objectID"])
        except Exception as e:
            log.error("hn_thread_search_error", error=str(e))

        return None

    async def _fetch_item(self, client: httpx.AsyncClient, item_id: int) -> dict:
        url = f"{HN_API}/item/{item_id}.json"
        response = await fetch_with_retry(client, url)
        return response.json()

    async def _process_comment(self, client: httpx.AsyncClient, comment_id: int) -> Job | None:
        """Fetch and parse a single HN comment into a Job."""
        try:
            comment = await self._fetch_item(client, comment_id)
            if comment.get("deleted") or comment.get("dead"):
                return None

            text = comment.get("text", "")
            if not text:
                return None

            # Parse the comment text
            parsed = self._parse_hn_comment(text)
            if not parsed:
                return None

            return Job(
                external_id=str(comment_id),
                source=JobSource.HN_HIRING,
                title=parsed.get("title", "Unknown Role"),
                company=parsed.get("company", "Unknown"),
                location=parsed.get("location", ""),
                description=self._clean_html(text),
                url=f"https://news.ycombinator.com/item?id={comment_id}",
                apply_url=parsed.get("apply_url"),
                raw_data={"hn_comment_id": comment_id},
            )
        except Exception as e:
            log.debug("hn_comment_parse_error", comment_id=comment_id, error=str(e))
            return None

    def _parse_hn_comment(self, html_text: str) -> dict | None:
        """Parse a HN Who's Hiring comment to extract structured data.

        HN comments typically start with: Company | Role | Location | Remote | URL
        """
        text = self._clean_html(html_text)
        lines = [line.strip() for line in text.split("\n") if line.strip()]

        if not lines:
            return None

        # First line usually has: Company | Title | Location | ...
        header = lines[0]
        parts = [p.strip() for p in re.split(r"\s*\|\s*", header)]

        result: dict = {}
        if len(parts) >= 1:
            result["company"] = parts[0]
        if len(parts) >= 2:
            result["title"] = parts[1]
        if len(parts) >= 3:
            result["location"] = parts[2]

        # Try to find URLs
        url_pattern = re.compile(r"https?://[^\s<>\"]+")
        urls = url_pattern.findall(html_text)
        if urls:
            result["apply_url"] = urls[0]

        # Full description is everything after the header
        result["description"] = "\n".join(lines[1:]) if len(lines) > 1 else header

        return result if result.get("company") else None

    @staticmethod
    def _clean_html(text: str) -> str:
        """Strip HTML tags and decode entities."""
        text = re.sub(r"<p>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)
        text = html.unescape(text)
        return text.strip()
