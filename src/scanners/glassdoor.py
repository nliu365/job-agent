"""Glassdoor job scanner via python-jobspy."""

from __future__ import annotations

import asyncio
from functools import partial

import structlog

from src.config import AppConfig
from src.models import Job, JobSource
from src.scanners.base import BaseScanner

log = structlog.get_logger()


class GlassdoorScanner(BaseScanner):
    def __init__(self, config: AppConfig):
        super().__init__(config)

    @property
    def source(self) -> JobSource:
        return JobSource.GLASSDOOR

    async def scan(self) -> list[Job]:
        all_jobs: list[Job] = []
        loop = asyncio.get_event_loop()

        for title in self.config.search.titles:
            for location in self.config.search.locations:
                try:
                    jobs = await loop.run_in_executor(
                        None,
                        partial(
                            self._scrape_jobs,
                            search_term=title,
                            location=location,
                        ),
                    )
                    all_jobs.extend(jobs)
                    log.info(
                        "glassdoor_search_complete",
                        search_term=title,
                        location=location,
                        jobs_found=len(jobs),
                    )
                except Exception as e:
                    log.error(
                        "glassdoor_search_error",
                        search_term=title,
                        location=location,
                        error=str(e),
                    )
                await self._rate_limit_pause()

        log.info("glassdoor_scan_complete", total_jobs=len(all_jobs))
        return all_jobs

    def _scrape_jobs(self, search_term: str, location: str) -> list[Job]:
        from jobspy import scrape_jobs

        proxies = [self.config.proxy_url] if self.config.proxy_url else None

        df = scrape_jobs(
            site_name=["glassdoor"],
            search_term=search_term,
            location=location,
            results_wanted=self.config.scanner.results_per_search,
            hours_old=self.config.scanner.hours_old,
            proxies=proxies,
        )

        return self._dataframe_to_jobs(df)

    def _dataframe_to_jobs(self, df) -> list[Job]:
        jobs: list[Job] = []
        for _, row in df.iterrows():
            try:
                job = Job(
                    external_id=str(row.get("id", row.get("job_url", ""))),
                    source=JobSource.GLASSDOOR,
                    title=str(row.get("title", "")),
                    company=str(row.get("company", "")),
                    location=str(row.get("location", "")),
                    description=str(row.get("description", "")),
                    url=str(row.get("job_url", "")),
                    apply_url=str(row.get("job_url", "")),
                    salary_min=self._parse_salary(row.get("min_amount")),
                    salary_max=self._parse_salary(row.get("max_amount")),
                )
                jobs.append(job)
            except Exception as e:
                log.debug("glassdoor_parse_row_error", error=str(e))
        return jobs

    @staticmethod
    def _parse_salary(value) -> int | None:
        if value is None or (isinstance(value, float) and str(value) == "nan"):
            return None
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return None
