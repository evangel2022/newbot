"""The job-registry interface the scheduling tool depends on."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from newbot.domain.job import ScheduledJob


class JobStorePort(Protocol):
    """Read and mutate a workspace's scheduled jobs."""

    def jobs(self) -> tuple[ScheduledJob, ...]:
        """Return every scheduled job."""
        ...

    def add(
        self,
        *,
        transport: str,
        conversation: str,
        prompt: str,
        next_run_at: datetime,
        every_seconds: float | None = None,
    ) -> ScheduledJob:
        """Append one job and return it."""
        ...

    def remove(self, job_id: str) -> bool:
        """Drop one job; return whether it existed."""
        ...
