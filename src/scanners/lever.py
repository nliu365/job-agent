"""Lever ATS public API scanner."""

from __future__ import annotations

import httpx
import structlog

from src.config import AppConfig
from src.models import Job, JobSource
from src.scanners.base import BaseScanner
from src.utils.retry import fetch_with_retry

log = structlog.get_logger()

BASE_URL = "https://api.lever.co/v0/postings"


class LeverScanner(BaseScanner):
    def __init__(self, config: AppConfig):
        super().__init__(config)
        self.companies = config.lever_companies

    @property
    def source(self) -> JobSource:
        return JobSource.LEVER

    async def scan(self) -> list[Job]:
        all_jobs: list[Job] = []

        async with httpx.AsyncClient(timeout=30) as client:
            for company in self.companies:
                try:
                    jobs = await self._scan_company(client, company.name, company.site)
                    all_jobs.extend(jobs)
                    log.info(
                        "lever_company_scanned",
                        company=company.name,
                        jobs_found=len(jobs),
                    )
                except Exception as e:
                    log.error(
                        "lever_company_error",
                        company=company.name,
                        error=str(e),
                    )
                await self._rate_limit_pause()

        log.info("lever_scan_complete", total_jobs=len(all_jobs))
        return all_jobs

    async def _scan_company(
        self, client: httpx.AsyncClient, company_name: str, site: str
    ) -> list[Job]:
        url = f"{BASE_URL}/{site}"
        response = await fetch_with_retry(client, url, params={"mode": "json"})
        postings = response.json()

        if not isinstance(postings, list):
            return []

        jobs: list[Job] = []
        for posting in postings:
            categories = posting.get("categories", {})
            location = categories.get("location", "") if isinstance(categories, dict) else ""

            job = Job(
                external_id=posting["id"],
                source=JobSource.LEVER,
                title=posting.get("text", ""),
                company=company_name,
                location=location,
                description=posting.get("descriptionPlain", ""),
                url=posting.get("hostedUrl", ""),
                apply_url=posting.get("applyUrl", ""),
                ats_type="lever",
                board_token=site,
                raw_data=posting,
            )
            jobs.append(job)

        return jobs
