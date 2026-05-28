"""Abstract base class for job application appliers."""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.models import ApplicationResult, Job, StructuredResume, TailoredOutput


class BaseApplier(ABC):
    @abstractmethod
    async def apply(
        self,
        job: Job,
        tailored: TailoredOutput,
        user_profile: dict,
        resume: StructuredResume | None = None,
    ) -> ApplicationResult:
        """Submit application. Return result with status and any error."""
        ...

    @abstractmethod
    def can_handle(self, job: Job) -> bool:
        """Return True if this applier can handle the given job."""
        ...
