"""Direct API submission to Lever job postings."""

from __future__ import annotations

import asyncio
import json

import httpx
import structlog

from src.appliers.base import BaseApplier
from src.models import ApplicationResult, Job, StructuredResume, TailoredOutput

log = structlog.get_logger()


class LeverAPIApplier(BaseApplier):
    def __init__(self, api_key: str):
        self.api_key = api_key

    def can_handle(self, job: Job) -> bool:
        return (
            job.ats_type == "lever"
            and job.board_token is not None
            and bool(self.api_key)
        )

    async def apply(
        self,
        job: Job,
        tailored: TailoredOutput,
        user_profile: dict,
        resume: StructuredResume | None = None,
    ) -> ApplicationResult:
        url = (
            f"https://api.lever.co/v0/postings"
            f"/{job.board_token}/{job.external_id}"
        )
        params = {"key": self.api_key}

        urls_data = {}
        if user_profile.get("linkedin_url"):
            urls_data["LinkedIn"] = user_profile["linkedin_url"]
        if user_profile.get("github"):
            urls_data["GitHub"] = user_profile["github"]
        if user_profile.get("website"):
            urls_data["Portfolio"] = user_profile["website"]

        first = user_profile.get("first_name", "")
        last = user_profile.get("last_name", "")

        data = {
            "name": f"{first} {last}".strip(),
            "email": user_profile.get("email", ""),
            "phone": user_profile.get("phone", ""),
            "org": user_profile.get("current_company", ""),
            "urls": json.dumps(urls_data),
            "comments": tailored.cover_letter,
            "source": "Direct Application",
        }

        files = {}
        if tailored.resume_pdf_path:
            files["resume"] = (
                "resume.pdf",
                open(tailored.resume_pdf_path, "rb"),
                "application/pdf",
            )

        log.info(
            "lever_api_applying",
            job_id=job.id,
            company=job.company,
            title=job.title,
        )

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    url, params=params, data=data, files=files
                )

                # Handle rate limiting
                if response.status_code == 429:
                    log.warning("lever_rate_limited", job_id=job.id)
                    await asyncio.sleep(2)
                    response = await client.post(
                        url, params=params, data=data, files=files
                    )

                result = response.json()

                if result.get("ok"):
                    log.info(
                        "lever_api_applied",
                        job_id=job.id,
                        application_id=result.get("applicationId"),
                    )
                    return ApplicationResult(
                        success=True,
                        application_id=result.get("applicationId"),
                        response_data=result,
                    )
                else:
                    error = result.get("error", "Unknown error")
                    log.error("lever_api_rejected", job_id=job.id, error=error)
                    return ApplicationResult(success=False, error=error)

        except Exception as e:
            log.error("lever_api_error", job_id=job.id, error=str(e))
            return ApplicationResult(success=False, error=str(e))
        finally:
            for _name, file_tuple in files.items():
                file_tuple[1].close()
