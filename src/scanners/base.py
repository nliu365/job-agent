"""Abstract base class for all job scanners."""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.config import AppConfig
from src.models import Job, JobSource
from src.utils.rate_limiter import rate_limiters


class BaseScanner(ABC):
    def __init__(self, config: AppConfig):
        self.config = config

    @abstractmethod
    async def scan(self) -> list[Job]:
        """Return list of discovered jobs from this source."""
        ...

    @property
    @abstractmethod
    def source(self) -> JobSource:
        ...

    async def _rate_limit_pause(self) -> None:
        await rate_limiters.acquire(self.source.value)
