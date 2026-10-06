"""Turn-level value types: status and budget."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class TurnStatus(StrEnum):
    """How a turn ended."""

    COMPLETED = "completed"
    BUDGET_EXCEEDED = "budget_exceeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class Budget:
    """Bounds the number of provider calls a single turn may make."""

    max_iterations: int
