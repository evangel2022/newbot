"""Journal value types for consolidated memory."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class JournalEntry:
    """One consolidated summary at a monotonic cursor position."""

    cursor: int
    timestamp: datetime
    summary: str
