"""Value types for delegated subagent tasks."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from newbot.domain.session import SessionKey


class SubagentStatus(StrEnum):
    """How a delegated task currently stands."""

    RUNNING = "running"
    COMPLETED = "completed"
    INCOMPLETE = "incomplete"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True, slots=True)
class SubagentTask:
    """A snapshot of one delegated task."""

    id: str
    status: SubagentStatus
    text: str


@dataclass(frozen=True, slots=True)
class SubagentTaskRecord:
    """The durable form of a task: its owner, its child, and its outcome."""

    id: str
    parent: SessionKey
    child: SessionKey
    status: SubagentStatus
    text: str
