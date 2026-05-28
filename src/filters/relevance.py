"""Multi-factor relevance scoring for job postings."""

from __future__ import annotations

import re

from thefuzz import fuzz

from src.config import SearchCriteria
from src.models import Job


def score_job(job: Job, criteria: SearchCriteria) -> float:
    """Score a job from 0.0 to 1.0 based on relevance to search criteria."""
    score = 0.0

    # Title match (weight: 0.4)
    title_score = max(
        (fuzz.token_sort_ratio(job.title.lower(), t.lower()) / 100.0 for t in criteria.titles),
        default=0.0,
    )
    score += 0.4 * title_score

    # Keyword match (weight: 0.3)
    desc_lower = job.description.lower()
    matched_keywords = sum(1 for k in criteria.keywords if k.lower() in desc_lower)
    keyword_ratio = min(matched_keywords / max(len(criteria.keywords) * 0.3, 1), 1.0)
    score += 0.3 * keyword_ratio

    # Experience level match (weight: 0.2)
    years = parse_years_experience(job.description)
    if years is not None:
        if criteria.min_years_experience <= years <= criteria.max_years_experience:
            score += 0.2
        elif abs(years - 10) <= 3:
            score += 0.1
    else:
        score += 0.1  # Unknown experience, assume possible match

    # Location match (weight: 0.1)
    job_loc_lower = job.location.lower()
    if any(loc.lower() in job_loc_lower for loc in criteria.locations):
        score += 0.1
    elif criteria.remote_ok and "remote" in job_loc_lower:
        score += 0.1

    # Negative signals
    for neg in criteria.negative_keywords:
        neg_lower = neg.lower()
        if neg_lower in job.title.lower():
            score -= 0.3
        elif neg_lower in desc_lower:
            score -= 0.1

    return max(0.0, min(1.0, score))


def parse_years_experience(description: str) -> int | None:
    """Extract years of experience requirement from job description.

    Looks for patterns like:
      - "5+ years"
      - "5-10 years"
      - "at least 8 years"
      - "minimum 7 years of experience"
    """
    patterns = [
        r"(\d+)\+?\s*(?:to\s*\d+\s*)?years?\s*(?:of\s+)?(?:experience|exp)",
        r"(\d+)\s*-\s*\d+\s*years?\s*(?:of\s+)?(?:experience|exp)",
        r"(?:at\s+least|minimum|min\.?)\s*(\d+)\s*years?",
        r"(\d+)\+\s*years?",
    ]

    for pattern in patterns:
        match = re.search(pattern, description, re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except (ValueError, IndexError):
                continue

    return None
