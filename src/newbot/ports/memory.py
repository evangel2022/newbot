"""The consolidated-memory journal interface."""

from __future__ import annotations

from typing import Protocol

from newbot.domain.journal import JournalEntry


class JournalPort(Protocol):
    """Append-only, cursor-based store of compacted-turn summaries."""

    async def append(self, summary: str) -> None:
        """Append one summary as the next journal entry."""
        ...

    async def entries(self) -> tuple[JournalEntry, ...]:
        """Return every entry in cursor order, oldest first."""
        ...
