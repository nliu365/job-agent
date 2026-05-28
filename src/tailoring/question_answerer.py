"""Generate answers to mandatory ATS application questions using Claude."""

from __future__ import annotations

import json
import re

import anthropic
import structlog

from src.models import Job, StructuredResume

log = structlog.get_logger()

# Common questions Claude can answer deterministically without an API call
_DETERMINISTIC: dict[str, str | None] = {
    # Work authorization
    r"authorized.*(work|employ).*us|us.*work.*authoriz": "Yes",
    r"work.*authoriz|authoriz.*work|legally.*work|eligible.*work": "Yes",
    r"citizen.*united states|us citizen": "No",
    # Sponsorship
    r"require.*sponsor|need.*sponsor|visa.*sponsor|sponsor.*visa|require.*visa": "No",
    r"will you now.*require.*sponsor|currently require.*sponsor": "No",
    # Remote / on-site
    r"willing.*work.*remote|comfortable.*remote|remote.*position": "Yes",
    r"willing.*relocat": "No",
    # EEO — prefer-not-to-answer
    r"gender|race|ethnicity|veteran|disability|sexual orient": None,
}

ANSWER_PROMPT = """You are a job application assistant. Given the applicant's resume summary and a list of application questions, provide concise, honest answers for each question.

APPLICANT SUMMARY:
- Name: {name}
- Summary: {summary}
- Total Experience: ~13 years software engineering, ~5 years ML/AI Infrastructure
- Education: Master's in Computer Science, University of Florida
- Current/Recent Role: Senior Software Engineer (AI/ML Infrastructure) at Roche
- Key Skills: Python, PyTorch, vLLM, HuggingFace, LangChain, Kubernetes, AWS/GCP, MLOps, RAG, LLM fine-tuning
- Work Authorization: Authorized to work in the US, does NOT require sponsorship
- Location: Open to remote or San Francisco Bay Area / New York / Seattle
- LinkedIn: {linkedin}

JOB CONTEXT:
Title: {title}
Company: {company}

QUESTIONS (JSON):
{questions_json}

Return ONLY a JSON object mapping each question "id" to an answer string. For EEO/demographic questions (race, gender, disability, veteran status), set the value to "Prefer not to answer". For required free-text questions, give concise professional answers (1-3 sentences max). For numeric experience questions, calculate based on the resume. For yes/no questions, answer Yes or No only.

Example output format:
{{"q_123": "Yes", "q_456": "5 years", "q_789": "I am authorized to work in the US without sponsorship."}}"""


class ATSQuestion:
    """Represents a single ATS application question."""

    def __init__(
        self,
        question_id: str,
        label: str,
        required: bool = True,
        field_type: str = "input_text",
        values: list[dict] | None = None,
    ):
        self.question_id = question_id
        self.label = label
        self.required = required
        self.field_type = field_type  # input_text, textarea, multi_value_single_select, etc.
        self.values = values or []  # For dropdown/radio questions

    def to_dict(self) -> dict:
        d: dict = {
            "id": self.question_id,
            "label": self.label,
            "type": self.field_type,
            "required": self.required,
        }
        if self.values:
            d["values"] = self.values
        return d

    @classmethod
    def from_greenhouse(cls, q: dict) -> "ATSQuestion":
        """Parse from Greenhouse API question dict."""
        return cls(
            question_id=str(q.get("id", q.get("name", ""))),
            label=q.get("label", q.get("name", "")),
            required=q.get("required", False),
            field_type=q.get("type", "input_text"),
            values=[{"id": str(v.get("id", "")), "label": v.get("label", "")}
                    for v in q.get("values", [])],
        )


class QuestionAnswerer:
    """Uses Claude to generate answers to mandatory ATS questions."""

    def __init__(self, api_key: str):
        self.client = anthropic.AsyncAnthropic(api_key=api_key)

    def _try_deterministic(self, question: ATSQuestion) -> str | None:
        """Return a fast deterministic answer for common questions, or None."""
        label_lower = question.label.lower()
        for pattern, answer in _DETERMINISTIC.items():
            if re.search(pattern, label_lower, re.IGNORECASE):
                if answer is None:
                    # EEO question — pick the first "prefer not to answer" option if available
                    for v in question.values:
                        if re.search(r"prefer.*(not|decline)|decline", v.get("label", ""), re.IGNORECASE):
                            return v["label"]
                    return "Prefer not to answer"
                # For dropdown/radio questions, match the answer to an available option
                if question.values:
                    for v in question.values:
                        if v.get("label", "").lower().startswith(answer.lower()):
                            return v["label"]
                return answer
        return None

    async def answer(
        self,
        questions: list[ATSQuestion],
        resume: StructuredResume,
        job: Job,
    ) -> dict[str, str]:
        """Generate answers for all questions. Returns {question_id: answer}."""
        if not questions:
            return {}

        answers: dict[str, str] = {}
        remaining: list[ATSQuestion] = []

        # Fast-path deterministic answers
        for q in questions:
            det = self._try_deterministic(q)
            if det is not None:
                answers[q.question_id] = det
                log.debug("question_deterministic", question_id=q.question_id, label=q.label, answer=det)
            else:
                remaining.append(q)

        if not remaining:
            return answers

        # Use Claude for the rest
        log.info("question_answering_with_claude", job_id=job.id, count=len(remaining))
        prompt = ANSWER_PROMPT.format(
            name=resume.name,
            summary=resume.summary[:500],
            linkedin=resume.linkedin_url or "https://linkedin.com/in/liuning1",
            title=job.title,
            company=job.company,
            questions_json=json.dumps([q.to_dict() for q in remaining], indent=2),
        )

        try:
            response = await self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text
            raw = self._extract_json(text)
            claude_answers: dict = json.loads(raw)
            answers.update(claude_answers)
            log.info("question_answered_by_claude", job_id=job.id, answered=len(claude_answers))
        except Exception as e:
            log.error("question_answering_failed", job_id=job.id, error=str(e))
            # Fall back to blanks for required questions
            for q in remaining:
                if q.required:
                    answers.setdefault(q.question_id, "")

        return answers

    @staticmethod
    def _extract_json(text: str) -> str:
        if "```json" in text:
            return text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            return text.split("```")[1].split("```")[0].strip()
        # Find first {...}
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return m.group(0)
        return text.strip()
