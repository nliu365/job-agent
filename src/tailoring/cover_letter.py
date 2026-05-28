"""Generate targeted cover letters using Claude API."""

from __future__ import annotations

import anthropic
import structlog

from src.models import Job, StructuredResume

log = structlog.get_logger()

COVER_LETTER_PROMPT = """Write a concise, professional cover letter for this job application.

CANDIDATE:
Name: {name}
Current Role: {current_title} at {current_company}
Key Skills: {skills}

JOB:
Title: {title}
Company: {company}
Description:
{description}

GUIDELINES:
- 3-4 paragraphs maximum
- Opening: mention the specific role and why you're interested in this company
- Body: connect 2-3 specific experiences to job requirements
- Closing: express enthusiasm and availability
- Professional but not generic -- reference specific things about the company/role
- Do not repeat the entire resume; highlight what makes you uniquely qualified
- Do not include a header or address block -- just the letter body
- Sign off with the candidate's name"""


class CoverLetterGenerator:
    def __init__(self, api_key: str):
        self.client = anthropic.AsyncAnthropic(api_key=api_key)

    async def generate(self, resume: StructuredResume, job: Job) -> str:
        """Generate a cover letter tailored to the job."""
        current_title = ""
        current_company = ""
        if resume.experience:
            current_title = resume.experience[0].title
            current_company = resume.experience[0].company

        prompt = COVER_LETTER_PROMPT.format(
            name=resume.name,
            current_title=current_title,
            current_company=current_company,
            skills=", ".join(resume.skills[:10]),
            title=job.title,
            company=job.company,
            description=job.description[:3000],
        )

        log.info("generating_cover_letter", job_id=job.id, company=job.company)

        response = await self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )

        cover_letter = response.content[0].text
        log.info("cover_letter_generated", job_id=job.id)
        return cover_letter
