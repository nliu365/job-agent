"""SQLite-backed application tracking."""

from __future__ import annotations

from datetime import datetime

import aiosqlite

from src.models import ApplicationStatus


class ApplicationStore:
    def __init__(self, db_path: str = "data/jobs.db"):
        self.db_path = db_path

    async def create_application(self, job_id: str, status: ApplicationStatus) -> str:
        import uuid

        app_id = uuid.uuid4().hex
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO applications (id, job_id, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)""",
                (app_id, job_id, status.value, now, now),
            )
            await db.commit()
        return app_id

    async def update_status(
        self,
        app_id: str,
        status: ApplicationStatus,
        error_message: str | None = None,
    ) -> None:
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            if status == ApplicationStatus.APPLIED:
                await db.execute(
                    """UPDATE applications
                    SET status = ?, applied_at = ?, updated_at = ?, error_message = NULL
                    WHERE id = ?""",
                    (status.value, now, now, app_id),
                )
            elif status == ApplicationStatus.FAILED:
                await db.execute(
                    """UPDATE applications
                    SET status = ?, error_message = ?, updated_at = ?,
                        attempt_count = attempt_count + 1
                    WHERE id = ?""",
                    (status.value, error_message, now, app_id),
                )
            else:
                await db.execute(
                    """UPDATE applications SET status = ?, updated_at = ? WHERE id = ?""",
                    (status.value, now, app_id),
                )
            await db.commit()

    async def set_tailored_paths(
        self, app_id: str, resume_path: str, cover_letter_path: str
    ) -> None:
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """UPDATE applications
                SET tailored_resume_path = ?, cover_letter_path = ?, updated_at = ?
                WHERE id = ?""",
                (resume_path, cover_letter_path, now, app_id),
            )
            await db.commit()

    async def get_application_for_job(self, job_id: str) -> dict | None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM applications WHERE job_id = ? ORDER BY created_at DESC LIMIT 1",
                (job_id,),
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_applications_by_status(self, status: ApplicationStatus) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM applications WHERE status = ? ORDER BY created_at DESC",
                (status.value,),
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_failed_retryable(self, max_attempts: int = 2) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM applications WHERE status = 'failed' AND attempt_count < ?",
                (max_attempts,),
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
