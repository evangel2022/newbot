"""Integration tests for one curation pass over durable memory files."""

from __future__ import annotations

from pathlib import Path

import pytest

from newbot.adapters.stores.fs_vault import FsVault
from newbot.adapters.stores.json_cursors import JsonCursors
from newbot.adapters.stores.jsonl_journal import JsonlJournal
from newbot.domain.curation import CurationEdit, CurationOutcome
from newbot.domain.errors import CurationError
from newbot.memory.curator import Curator
from newbot.memory.layout import MemoryLayout
from newbot.policy.redaction import Redactor
from support import ScriptedCurator

_Parts = tuple[MemoryLayout, JsonlJournal, JsonCursors, FsVault]


def _parts(tmp_path: Path) -> _Parts:
    layout = MemoryLayout(tmp_path / "ws")
    return (
        layout,
        JsonlJournal(layout.journal),
        JsonCursors(layout.cursors),
        FsVault(tmp_path / "vault", layout.workspace_root),
    )


def _curator(
    parts: _Parts, interpreter: ScriptedCurator, redactor: Redactor | None = None
) -> Curator:
    layout, journal, cursors, vault = parts
    return Curator(
        layout=layout,
        journal=journal,
        cursors=cursors,
        versioning=vault,
        redactor=Redactor(()) if redactor is None else redactor,
        interpreter=interpreter,
    )


async def test_curation_applies_an_edit_and_advances_the_cursor(tmp_path: Path) -> None:
    parts = _parts(tmp_path)
    layout, journal, cursors, vault = parts
    await journal.append("first summary")
    await journal.append("second summary")
    interpreter = ScriptedCurator(
        [CurationEdit(path="memory/knowledge.md", content="- decided X\n")]
    )

    outcome = await _curator(parts, interpreter).run()

    assert outcome == CurationOutcome(changed=("memory/knowledge.md",), consumed=2)
    assert layout.knowledge.read_text(encoding="utf-8") == "- decided X\n"
    assert len(await vault.history(layout.knowledge)) == 1
    assert await cursors.read() == 2
    entries, files = interpreter.calls[0]
    assert [entry.summary for entry in entries] == ["first summary", "second summary"]
    assert [file.path for file in files] == [
        "persona.md",
        "user.md",
        "memory/knowledge.md",
    ]
    assert all(file.content == "" for file in files)


async def test_curation_consumes_only_entries_newer_than_the_cursor(
    tmp_path: Path,
) -> None:
    parts = _parts(tmp_path)
    layout, journal, cursors, vault = parts
    await journal.append("first summary")
    await cursors.write(1)
    interpreter = ScriptedCurator([])

    outcome = await _curator(parts, interpreter).run()

    assert outcome == CurationOutcome(changed=(), consumed=1)
    assert interpreter.calls == []
    assert not layout.knowledge.exists()
    assert await vault.history(layout.knowledge) == ()


async def test_curation_writes_nothing_when_content_is_unchanged(
    tmp_path: Path,
) -> None:
    parts = _parts(tmp_path)
    layout, journal, _, vault = parts
    await journal.append("summary")
    layout.knowledge.parent.mkdir(parents=True, exist_ok=True)
    layout.knowledge.write_text("same", encoding="utf-8")
    interpreter = ScriptedCurator([CurationEdit(path="memory/knowledge.md", content="same")])

    outcome = await _curator(parts, interpreter).run()

    assert outcome.changed == ()
    assert outcome.consumed == 1
    assert await vault.history(layout.knowledge) == ()


async def test_an_unknown_target_is_rejected_without_advancing_the_cursor(
    tmp_path: Path,
) -> None:
    parts = _parts(tmp_path)
    _, journal, cursors, _ = parts
    await journal.append("summary")
    interpreter = ScriptedCurator([CurationEdit(path="../../escape.md", content="x")])

    with pytest.raises(CurationError):
        await _curator(parts, interpreter).run()

    assert await cursors.read() == 0
    assert not (tmp_path / "escape.md").exists()


async def test_curation_offers_existing_durable_content_to_the_interpreter(
    tmp_path: Path,
) -> None:
    parts = _parts(tmp_path)
    layout, journal, _, _ = parts
    await journal.append("summary")
    layout.persona.parent.mkdir(parents=True, exist_ok=True)
    layout.persona.write_text("voice", encoding="utf-8")
    interpreter = ScriptedCurator([])

    await _curator(parts, interpreter).run()

    files = interpreter.calls[0][1]
    assert [file.content for file in files] == ["voice", "", ""]


async def test_curation_redacts_secrets_before_writing(tmp_path: Path) -> None:
    parts = _parts(tmp_path)
    layout, journal, _, _ = parts
    await journal.append("summary")
    interpreter = ScriptedCurator(
        [CurationEdit(path="memory/knowledge.md", content="token sk-live-secret")]
    )

    await _curator(parts, interpreter, Redactor(["sk-live-secret"])).run()

    written = layout.knowledge.read_text(encoding="utf-8")
    assert "sk-live-secret" not in written
    assert "[redacted]" in written
