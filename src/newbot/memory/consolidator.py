"""Consolidation: append sanitized compaction summaries to the journal."""

from __future__ import annotations

from newbot.memory.sanitizer import MAX_SUMMARY_CHARS, sanitize
from newbot.policy.redaction import Redactor
from newbot.ports.memory import JournalPort


class Consolidator:
    """Owns the sanitized journal write path for compacted turns."""

    def __init__(self, *, journal: JournalPort, redactor: Redactor) -> None:
        self._journal = journal
        self._redactor = redactor

    async def consolidate(self, summary: str) -> None:
        """Append one sanitized summary as the next journal entry."""
        await self._journal.append(
            sanitize(summary, self._redactor, limit=MAX_SUMMARY_CHARS)
        )
