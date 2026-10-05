"""Contract tests for the JSONL consolidation journal."""

from __future__ import annotations

from pathlib import Path

import pytest

from newbot.adapters.stores.jsonl_journal import JsonlJournal
from newbot.domain.errors import JournalError


async def test_entries_are_cursor_ordered_and_survive_a_new_instance(
    tmp_path: Path,
) -> None:
    path = tmp_path / "memory" / "journal.jsonl"
    journal = JsonlJournal(path)

    await journal.append("first summary")
    await journal.append("second summary")

    entries = await JsonlJournal(path).entries()

    assert [entry.cursor for entry in entries] == [1, 2]
    assert [entry.summary for entry in entries] == ["first summary", "second summary"]
    assert all(entry.timestamp.tzinfo is not None for entry in entries)


async def test_empty_journal_has_no_entries(tmp_path: Path) -> None:
    journal = JsonlJournal(tmp_path / "memory" / "journal.jsonl")

    assert await journal.entries() == ()


async def test_malformed_entry_raises_journal_error(tmp_path: Path) -> None:
    path = tmp_path / "memory" / "journal.jsonl"
    journal = JsonlJournal(path)
    await journal.append("first")
    path.write_text(path.read_text(encoding="utf-8") + "{not json}\n", encoding="utf-8")

    with pytest.raises(JournalError):
        await journal.entries()

