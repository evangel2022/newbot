"""JSONL journal of consolidated summaries, appended under a lock."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from newbot.domain.errors import JournalError
from newbot.domain.journal import JournalEntry

_MAX_SUMMARY = 4000
_TRUNCATED = "...[truncated]"


class _WireEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    summary: str


class JsonlJournal:
    """Stores consolidated summaries as one JSONL line per entry."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = asyncio.Lock()

    async def append(self, summary: str) -> None:
        async with self._lock:
            await asyncio.to_thread(self._append, summary)

    async def entries(self) -> tuple[JournalEntry, ...]:
        return await asyncio.to_thread(self._read)

    def _append(self, summary: str) -> None:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "summary": _bounded(summary),
        }
        line = json.dumps(payload, ensure_ascii=False)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(f"{line}\n")
        except OSError as exc:
            raise JournalError(
                f"cannot write journal {self._path.name}: {exc}"
            ) from exc

    def _read(self) -> tuple[JournalEntry, ...]:
        try:
            text = self._path.read_text(encoding="utf-8") if self._path.is_file() else ""
        except OSError as exc:
            raise JournalError(
                f"cannot read journal {self._path.name}: {exc}"
            ) from exc
        entries: list[JournalEntry] = []
        for number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            wire = _parse_entry(line, self._path.name, number)
            entries.append(
                JournalEntry(
                    cursor=len(entries) + 1,
                    timestamp=wire.timestamp,
                    summary=wire.summary,
                )
            )
        return tuple(entries)


def _parse_entry(line: str, filename: str, number: int) -> _WireEntry:
    try:
        return _WireEntry.model_validate_json(line)
    except (ValidationError, ValueError) as exc:
        raise JournalError(
            f"invalid journal entry in {filename} line {number}: {exc}"
        ) from exc


def _bounded(summary: str) -> str:
    text = summary.strip()
    if len(text) <= _MAX_SUMMARY:
        return text
    return text[:_MAX_SUMMARY] + _TRUNCATED
