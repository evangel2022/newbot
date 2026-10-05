"""Integration tests for consolidating compaction summaries into the journal."""

from __future__ import annotations

from pathlib import Path

from newbot.adapters.stores.jsonl_journal import JsonlJournal
from newbot.memory.consolidator import Consolidator
from newbot.policy.redaction import Redactor


async def test_consolidate_redacts_secrets_and_bounds_the_entry(tmp_path: Path) -> None:
    journal = JsonlJournal(tmp_path / "memory" / "journal.jsonl")
    consolidator = Consolidator(journal=journal, redactor=Redactor(["sk-live-secret"]))

    await consolidator.consolidate(f"token sk-live-secret {'x' * 5000}")

    entry = (await journal.entries())[0]
    assert entry.summary.startswith("token [redacted]")
    assert "sk-live-secret" not in entry.summary
    assert len(entry.summary) < 5000
