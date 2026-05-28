"""Job deduplication across sources."""

from __future__ import annotations

import re

from thefuzz import fuzz

from src.models import Job

FUZZY_THRESHOLD = 85


def normalize_company(name: str) -> str:
    """Normalize company name for comparison."""
    name = name.lower().strip()
    # Remove common suffixes
    for suffix in [", inc.", ", inc", " inc.", " inc", ", llc", " llc", ", ltd", " ltd", " co."]:
        name = name.removesuffix(suffix)
    # Remove extra whitespace
    name = re.sub(r"\s+", " ", name)
    return name


def normalize_title(title: str) -> str:
    """Normalize job title for comparison."""
    title = title.lower().strip()
    # Remove common prefixes/qualifiers
    for prefix in ["senior ", "sr. ", "sr ", "staff ", "principal ", "lead "]:
        title = title.removeprefix(prefix)
    title = re.sub(r"\s+", " ", title)
    return title


def make_dedup_key(job: Job) -> str:
    """Create a normalized key for fuzzy dedup."""
    company = normalize_company(job.company)
    title = normalize_title(job.title)
    # Extract city from location
    location = job.location.lower().split(",")[0].strip() if job.location else ""
    return f"{company}|{title}|{location}"


def is_duplicate(new_job: Job, existing_jobs: list[Job]) -> bool:
    """Check if a job is a fuzzy duplicate of any existing job."""
    new_key = make_dedup_key(new_job)

    for existing in existing_jobs:
        existing_key = make_dedup_key(existing)

        # Exact key match
        if new_key == existing_key:
            return True

        # Fuzzy match on company + title
        company_score = fuzz.ratio(
            normalize_company(new_job.company),
            normalize_company(existing.company),
        )
        title_score = fuzz.token_sort_ratio(
            normalize_title(new_job.title),
            normalize_title(existing.title),
        )

        if company_score >= FUZZY_THRESHOLD and title_score >= FUZZY_THRESHOLD:
            return True

    return False


def deduplicate_jobs(jobs: list[Job]) -> list[Job]:
    """Remove duplicate jobs from a list, keeping the first occurrence."""
    unique: list[Job] = []
    for job in jobs:
        if not is_duplicate(job, unique):
            unique.append(job)
    return unique
