"""Curation: shape new journal entries into minimal durable-file edits."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from newbot.domain.curation import CurationEdit, CurationOutcome, DurableFile
from newbot.domain.errors import CurationError
from newbot.memory.layout import MemoryLayout
from newbot.memory.sanitizer import MAX_DURABLE_CHARS, sanitize
from newbot.policy.redaction import Redactor
from newbot.ports.memory import CurationPort, CursorPort, JournalPort
from newbot.ports.versioning import VersioningPort


class Curator:
    """Consumes new journal entries and applies the interpreter's edits."""

    def __init__(
        self,
        *,
        layout: MemoryLayout,
        journal: JournalPort,
        cursors: CursorPort,
        versioning: VersioningPort,
        redactor: Redactor,
        interpreter: CurationPort,
    ) -> None:
        self._layout = layout
        self._journal = journal
        self._cursors = cursors
        self._versioning = versioning
        self._redactor = redactor
        self._interpreter = interpreter

    async def run(self) -> CurationOutcome:
        """Interpret pending journal entries and write the resulting edits."""
        consumed = await self._cursors.read()
        pending = tuple(
            entry for entry in await self._journal.entries() if entry.cursor > consumed
        )
        if not pending:
            return CurationOutcome(changed=(), consumed=consumed)
        targets = self._targets()
        files = tuple(
            DurableFile(path=relative, content=_read_text(path))
            for relative, path in targets.items()
        )
        edits = await self._interpreter.interpret(pending, files)
        changed, change_set = await self._apply(edits, targets, files)
        cursor = pending[-1].cursor
        await self._cursors.write(cursor)
        return CurationOutcome(
            changed=changed, consumed=cursor, change_set=change_set
        )

    def _targets(self) -> dict[str, Path]:
        return {
            path.relative_to(self._layout.workspace_root).as_posix(): path
            for path in self._layout.durable_files
        }

    async def _apply(
        self,
        edits: Sequence[CurationEdit],
        targets: Mapping[str, Path],
        files: Sequence[DurableFile],
    ) -> tuple[tuple[str, ...], str | None]:
        current = {file.path: file.content for file in files}
        writes: dict[str, tuple[Path, str]] = {}
        for edit in edits:
            target = targets.get(edit.path)
            if target is None:
                raise CurationError(f"curation proposed an unknown file: {edit.path}")
            content = sanitize(
                edit.content, self._redactor, limit=MAX_DURABLE_CHARS
            )
            if current.get(edit.path) == content:
                continue
            writes[edit.path] = (target, content)
            current[edit.path] = content
        if not writes:
            return (), None
        change_set = await self._versioning.write_set(tuple(writes.values()))
        return tuple(writes), change_set


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8") if path.is_file() else ""
    except OSError as exc:
        raise CurationError(f"cannot read {path.name}: {exc}") from exc
