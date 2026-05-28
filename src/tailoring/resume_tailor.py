"""Tailor resume for a specific job using Claude API."""

from __future__ import annotations

import json

import anthropic
import structlog

from src.models import Job, StructuredResume

log = structlog.get_logger()

TAILOR_PROMPT = """You are an expert resume writer. Tailor this resume for the specific job below.

RULES:
- Do NOT fabricate experience or skills the candidate doesn't have
- DO reorder bullets to emphasize relevant experience first
- DO adjust the summary/objective to target this role
- DO reorder skills to place most relevant ones first
- DO mirror terminology from the job description where truthful
- Keep the resume to 1-2 pages worth of content
- Return ONLY valid JSON with the same schema as the input

RESUME (JSON):
{resume_json}

JOB DESCRIPTION:
Title: {title}
Company: {company}
Description:
{description}

Return the tailored resume as JSON with the exact same structure."""


class ResumeTailor:
    def __init__(self, api_key: str):
        self.client = anthropic.AsyncAnthropic(api_key=api_key)

    async def tailor(self, resume: StructuredResume, job: Job) -> StructuredResume:
        """Tailor a resume for a specific job posting."""
        prompt = TAILOR_PROMPT.format(
            resume_json=resume.model_dump_json(indent=2),
            title=job.title,
            company=job.company,
            description=job.description[:4000],  # Truncate long descriptions
        )

        log.info("tailoring_resume", job_id=job.id, company=job.company, title=job.title)

        response = await self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )

        response_text = response.content[0].text
        json_text = self._extract_json(response_text)

        tailored = StructuredResume.model_validate_json(json_text)
        log.info("resume_tailored", job_id=job.id)
        return tailored

    @staticmethod
    def _extract_json(text: str) -> str:
        """Extract JSON from a response that may include markdown code blocks."""
        if "```json" in text:
            return text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            return text.split("```")[1].split("```")[0].strip()
        return text.strip()
