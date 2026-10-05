"""Version records for reversible durable-file writes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class FileVersion:
    """One recorded state of a file inside the agent workspace."""

    version_id: str
    path: str
    timestamp: datetime
    size: int
    change_set: str | None = None
