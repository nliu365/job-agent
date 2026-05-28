"""Greenhouse ATS public API scanner."""

from __future__ import annotations

import httpx
import structlog

from src.config import AppConfig
from src.models import Job, JobSource
from src.scanners.base import BaseScanner
from src.utils.retry import fetch_with_retry

log = structlog.get_logger()

BASE_URL = "https://boards-api.greenhouse.io/v1/boards"


class GreenhouseScanner(BaseScanner):
    def __init__(self, config: AppConfig):
        super().__init__(config)
        self.companies = config.greenhouse_companies

    @property
    def source(self) -> JobSource:
        return JobSource.GREENHOUSE

    async def scan(self) -> list[Job]:
        all_jobs: list[Job] = []

        async with httpx.AsyncClient(timeout=30) as client:
            for company in self.companies:
                try:
                    jobs = await self._scan_company(client, company.name, company.board_token)
                    all_jobs.extend(jobs)
                    log.info(
                        "greenhouse_company_scanned",
                        company=company.name,
                        jobs_found=len(jobs),
                    )
                except Exception as e:
                    log.error(
                        "greenhouse_company_error",
                        company=company.name,
                        error=str(e),
                    )
                await self._rate_limit_pause()

        log.info("greenhouse_scan_complete", total_jobs=len(all_jobs))
        return all_jobs

    async def _scan_company(
        self, client: httpx.AsyncClient, company_name: str, board_token: str
    ) -> list[Job]:
        url = f"{BASE_URL}/{board_token}/jobs"
        response = await fetch_with_retry(client, url, params={"content": "true"})
        data = response.json()

        jobs: list[Job] = []
        for job_data in data.get("jobs", []):
            title = job_data.get("title", "")
            location_data = job_data.get("location", {})
            location_name = location_data.get("name", "") if isinstance(location_data, dict) else ""

            job = Job(
                external_id=str(job_data["id"]),
                source=JobSource.GREENHOUSE,
                title=title,
                company=company_name,
                location=location_name,
                description=job_data.get("content", ""),
                url=job_data.get("absolute_url", ""),
                apply_url=job_data.get("absolute_url", ""),
                ats_type="greenhouse",
                board_token=board_token,
                raw_data=job_data,
            )
            jobs.append(job)

        return jobs
