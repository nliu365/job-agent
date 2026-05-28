"""Direct API submission to Greenhouse job boards."""

from __future__ import annotations

import base64

import httpx
import structlog

from src.appliers.base import BaseApplier
from src.models import ApplicationResult, Job, StructuredResume, TailoredOutput
from src.tailoring.question_answerer import ATSQuestion, QuestionAnswerer

log = structlog.get_logger()


class GreenhouseAPIApplier(BaseApplier):
    def __init__(self, api_key: str, question_answerer: QuestionAnswerer | None = None):
        self.api_key = api_key
        self.question_answerer = question_answerer

    def can_handle(self, job: Job) -> bool:
        return (
            job.ats_type == "greenhouse"
            and job.board_token is not None
            and bool(self.api_key)
        )

    async def _fetch_questions(
        self, client: httpx.AsyncClient, board_token: str, job_id: str
    ) -> list[ATSQuestion]:
        """Fetch required application questions from Greenhouse public API."""
        url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs/{job_id}"
        try:
            resp = await client.get(url, params={"questions": "true"}, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            raw_questions = data.get("questions", [])
            questions = [ATSQuestion.from_greenhouse(q) for q in raw_questions]
            # Skip fields already in the base form
            skip_labels = {
                "first name", "last name", "email", "phone", "resume", "cover letter",
            }
            questions = [
                q for q in questions
                if q.label.lower().strip() not in skip_labels
            ]
            log.info(
                "greenhouse_questions_fetched",
                board_token=board_token,
                job_id=job_id,
                count=len(questions),
            )
            return questions
        except Exception as e:
            log.warning("greenhouse_questions_fetch_failed", error=str(e))
            return []

    async def apply(
        self,
        job: Job,
        tailored: TailoredOutput,
        user_profile: dict,
        resume: StructuredResume | None = None,
    ) -> ApplicationResult:
        url = (
            f"https://boards-api.greenhouse.io/v1/boards"
            f"/{job.board_token}/jobs/{job.external_id}"
        )

        auth_value = base64.b64encode(f"{self.api_key}:".encode()).decode()
        headers = {"Authorization": f"Basic {auth_value}"}

        data: dict[str, str] = {
            "first_name": user_profile.get("first_name", ""),
            "last_name": user_profile.get("last_name", ""),
            "email": user_profile.get("email", ""),
            "phone": user_profile.get("phone", ""),
            "location": user_profile.get("location", ""),
        }

        files = {}
        if tailored.resume_pdf_path:
            files["resume"] = (
                "resume.pdf",
                open(tailored.resume_pdf_path, "rb"),
                "application/pdf",
            )
        if tailored.cover_letter_pdf_path:
            files["cover_letter"] = (
                "cover_letter.pdf",
                open(tailored.cover_letter_pdf_path, "rb"),
                "application/pdf",
            )

        log.info(
            "greenhouse_api_applying",
            job_id=job.id,
            company=job.company,
            title=job.title,
        )

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                # Fetch and answer custom questions
                if self.question_answerer and resume and job.board_token:
                    questions = await self._fetch_questions(
                        client, job.board_token, job.external_id
                    )
                    if questions:
                        answers = await self.question_answerer.answer(
                            questions, resume, job
                        )
                        for q in questions:
                            answer = answers.get(q.question_id, "")
                            if not answer:
                                continue
                            if q.field_type in (
                                "multi_value_single_select",
                                "multi_value_multi_select",
                            ):
                                matched_id = self._match_option_id(q, answer)
                                if matched_id:
                                    data[f"question[{q.question_id}][]"] = matched_id
                            else:
                                data[f"question[{q.question_id}]"] = answer

                response = await client.post(
                    url, data=data, files=files, headers=headers
                )
                response.raise_for_status()
                result = response.json()

                log.info("greenhouse_api_applied", job_id=job.id, response=result)
                return ApplicationResult(
                    success=True,
                    response_data=result,
                )
        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP {e.response.status_code}: {e.response.text}"
            log.error("greenhouse_api_error", job_id=job.id, error=error_msg)
            return ApplicationResult(success=False, error=error_msg)
        except Exception as e:
            log.error("greenhouse_api_error", job_id=job.id, error=str(e))
            return ApplicationResult(success=False, error=str(e))
        finally:
            for _name, file_tuple in files.items():
                file_tuple[1].close()

    @staticmethod
    def _match_option_id(question: ATSQuestion, answer: str) -> str | None:
        """Find the best-matching option id for a dropdown/radio answer."""
        answer_lower = answer.lower()
        # Exact match first
        for v in question.values:
            if v.get("label", "").lower() == answer_lower:
                return v.get("id")
        # Prefix/substring match
        for v in question.values:
            label = v.get("label", "").lower()
            if label.startswith(answer_lower[:4]) or answer_lower in label:
                return v.get("id")
        return None
