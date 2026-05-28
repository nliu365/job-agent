"""SQLite-backed job storage with deduplication."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import aiosqlite

from src.models import ApplicationStatus, Job, JobSource

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    external_id TEXT NOT NULL,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT DEFAULT '',
    description TEXT DEFAULT '',
    url TEXT NOT NULL,
    apply_url TEXT,
    salary_min INTEGER,
    salary_max INTEGER,
    date_posted TEXT,
    date_discovered TEXT NOT NULL,
    relevance_score REAL DEFAULT 0.0,
    ats_type TEXT,
    board_token TEXT,
    raw_data TEXT DEFAULT '{}',
    UNIQUE(source, external_id)
);

CREATE TABLE IF NOT EXISTS applications (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    status TEXT NOT NULL DEFAULT 'discovered',
    tailored_resume_path TEXT,
    cover_letter_path TEXT,
    applied_at TEXT,
    error_message TEXT,
    attempt_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_source_external ON jobs(source, external_id);
CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status);
CREATE INDEX IF NOT EXISTS idx_applications_job ON applications(job_id);
"""


class JobStore:
    def __init__(self, db_path: str = "data/jobs.db"):
        self.db_path = db_path

    async def initialize(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(SCHEMA)
            await db.commit()

    async def job_exists(self, source: str, external_id: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT 1 FROM jobs WHERE source = ? AND external_id = ?",
                (source, external_id),
            )
            return await cursor.fetchone() is not None

    async def insert_job(self, job: Job) -> bool:
        """Insert a job. Returns True if inserted, False if duplicate."""
        async with aiosqlite.connect(self.db_path) as db:
            try:
                await db.execute(
                    """INSERT INTO jobs
                    (id, external_id, source, title, company, location, description,
                     url, apply_url, salary_min, salary_max, date_posted, date_discovered,
                     relevance_score, ats_type, board_token, raw_data)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        job.id,
                        job.external_id,
                        job.source.value,
                        job.title,
                        job.company,
                        job.location,
                        job.description,
                        job.url,
                        job.apply_url,
                        job.salary_min,
                        job.salary_max,
                        job.date_posted.isoformat() if job.date_posted else None,
                        job.date_discovered.isoformat(),
                        job.relevance_score,
                        job.ats_type,
                        job.board_token,
                        json.dumps(job.raw_data),
                    ),
                )
                await db.commit()
                return True
            except aiosqlite.IntegrityError:
                return False

    async def get_jobs_by_status(self, status: ApplicationStatus) -> list[Job]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """SELECT j.* FROM jobs j
                JOIN applications a ON a.job_id = j.id
                WHERE a.status = ?
                ORDER BY
                    CASE j.ats_type WHEN 'greenhouse' THEN 0 WHEN 'lever' THEN 1 ELSE 2 END,
                    j.relevance_score DESC""",
                (status.value,),
            )
            rows = await cursor.fetchall()
            return [self._row_to_job(row) for row in rows]

    async def get_matched_jobs(self) -> list[Job]:
        return await self.get_jobs_by_status(ApplicationStatus.MATCHED)

    async def get_all_external_ids(self, source: str) -> set[str]:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT external_id FROM jobs WHERE source = ?", (source,)
            )
            rows = await cursor.fetchall()
            return {row[0] for row in rows}

    async def update_relevance_score(self, job_id: str, score: float) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE jobs SET relevance_score = ? WHERE id = ?", (score, job_id)
            )
            await db.commit()

    def _row_to_job(self, row: aiosqlite.Row) -> Job:
        return Job(
            id=row["id"],
            external_id=row["external_id"],
            source=JobSource(row["source"]),
            title=row["title"],
            company=row["company"],
            location=row["location"] or "",
            description=row["description"] or "",
            url=row["url"],
            apply_url=row["apply_url"],
            salary_min=row["salary_min"],
            salary_max=row["salary_max"],
            date_posted=datetime.fromisoformat(row["date_posted"])
            if row["date_posted"]
            else None,
            date_discovered=datetime.fromisoformat(row["date_discovered"]),
            relevance_score=row["relevance_score"] or 0.0,
            ats_type=row["ats_type"],
            board_token=row["board_token"],
            raw_data=json.loads(row["raw_data"]) if row["raw_data"] else {},
        )
