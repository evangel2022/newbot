"""The consolidated-memory journal interface."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from newbot.domain.curation import CurationEdit, DurableFile
from newbot.domain.journal import JournalEntry


class JournalPort(Protocol):
    """Append-only, cursor-based store of compacted-turn summaries."""

    async def append(self, summary: str) -> None:
        """Append one summary as the next journal entry."""
        ...

    async def entries(self) -> tuple[JournalEntry, ...]:
        """Return every entry in cursor order, oldest first."""
        ...


class CursorPort(Protocol):
    """Remembers how far curation has consumed the journal."""

    async def read(self) -> int:
        """Return the last consumed journal cursor, or ``0`` when never curated."""
        ...

    async def write(self, cursor: int) -> None:
        """Persist the last consumed journal cursor."""
        ...


class CurationPort(Protocol):
    """Interprets new journal entries into edits of the durable files."""

    async def interpret(
        self, entries: Sequence[JournalEntry], files: Sequence[DurableFile]
    ) -> tuple[CurationEdit, ...]:
        """Return the new content of each durable file that should change."""
        ...
