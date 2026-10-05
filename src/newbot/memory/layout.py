"""The documented memory file layout under one agent workspace."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class MemoryLayout:
    """Durable memory paths rooted at the agent workspace (architecture 搂9)."""

    workspace_root: Path

    @property
    def persona(self) -> Path:
        return self.workspace_root / "persona.md"

    @property
    def user(self) -> Path:
        return self.workspace_root / "user.md"

    @property
    def knowledge(self) -> Path:
        return self._memory_dir / "knowledge.md"

    @property
    def journal(self) -> Path:
        return self._memory_dir / "journal.jsonl"

    @property
    def cursors(self) -> Path:
        return self._memory_dir / "cursors.json"

    @property
    def _memory_dir(self) -> Path:
        return self.workspace_root / "memory"
