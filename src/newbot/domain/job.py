"""Value types for agent-created scheduled jobs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

Clock = Callable[[], datetime]


def utcnow() -> datetime:
    """The default clock: the current time in UTC."""
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class ScheduledJob:
    """One scheduled turn bound to the conversation that created it."""

    id: str
    transport: str
    conversation: str
    prompt: str
    next_run_at: datetime
    every_seconds: float | None = None
