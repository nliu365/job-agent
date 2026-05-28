"""Core data models for the job-alert system."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class JobSource(str, Enum):
    LINKEDIN = "linkedin"
    INDEED = "indeed"
    GLASSDOOR = "glassdoor"
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    HN_HIRING = "hn_hiring"


class ApplicationStatus(str, Enum):
    DISCOVERED = "discovered"
    MATCHED = "matched"
    TAILORING = "tailoring"
    READY_TO_APPLY = "ready_to_apply"
    APPLIED = "applied"
    FAILED = "failed"
    SKIPPED = "skipped"


class Job(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    external_id: str
    source: JobSource
    title: str
    company: str
    location: str = ""
    description: str = ""
    url: str
    apply_url: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    date_posted: datetime | None = None
    date_discovered: datetime = Field(default_factory=datetime.utcnow)
    relevance_score: float = 0.0
    ats_type: str | None = None
    board_token: str | None = None
    raw_data: dict = Field(default_factory=dict)


class ExperienceEntry(BaseModel):
    company: str
    title: str
    start_date: str = ""
    end_date: str = ""
    bullets: list[str] = Field(default_factory=list)

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def none_to_empty(cls, v: str | None) -> str:
        return v or ""


class EducationEntry(BaseModel):
    school: str
    degree: str
    field: str = ""
    start_date: str = ""
    end_date: str = ""
    gpa: str | None = None

    @field_validator("field", "start_date", "end_date", mode="before")
    @classmethod
    def none_to_empty(cls, v: str | None) -> str:
        return v or ""


class StructuredResume(BaseModel):
    name: str
    email: str
    phone: str = ""
    linkedin_url: str = ""
    location: str = ""
    summary: str = ""
    experience: list[ExperienceEntry] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    publications: list[str] = Field(default_factory=list)

    @field_validator("phone", "linkedin_url", "location", "summary", mode="before")
    @classmethod
    def none_to_empty(cls, v: str | None) -> str:
        return v or ""


class TailoredOutput(BaseModel):
    job_id: str
    tailored_resume: StructuredResume
    cover_letter: str
    resume_pdf_path: str = ""
    cover_letter_pdf_path: str = ""


class ApplicationResult(BaseModel):
    success: bool
    application_id: str | None = None
    error: str | None = None
    response_data: dict = Field(default_factory=dict)


class Application(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    job_id: str
    status: ApplicationStatus = ApplicationStatus.DISCOVERED
    tailored_output: TailoredOutput | None = None
    applied_at: datetime | None = None
    error_message: str | None = None
    attempt_count: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
