"""The subagent service the delegate tool depends on."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from newbot.domain.session import SessionKey
from newbot.domain.subagent import SubagentTask, SubagentTaskRecord


class SubagentPort(Protocol):
    """Runs delegated tasks as child turns with their own context."""

    async def run(
        self, task: str, *, parent: SessionKey, workspace_root: Path
    ) -> SubagentTask:
        """Run ``task`` for ``parent`` and return its final state."""
        ...

    async def start(
        self, task: str, *, parent: SessionKey, workspace_root: Path
    ) -> SubagentTask:
        """Start ``task`` in the background and return it while running."""
        ...

    async def status(self, task_id: str, *, parent: SessionKey) -> SubagentTask:
        """Return one task's current state; only its origin may read it."""
        ...

    async def wait(self, task_id: str, *, parent: SessionKey) -> SubagentTask:
        """Wait for one task to finish; only its origin may wait on it."""
        ...

    async def cancel(self, task_id: str, *, parent: SessionKey) -> SubagentTask:
        """Cancel one task; only its origin may cancel it."""
        ...


class SubagentTaskStorePort(Protocol):
    """Durable storage for subagent task records."""

    def load(self) -> tuple[SubagentTaskRecord, ...]:
        """Return every stored task record."""
        ...

    def save(self, records: Sequence[SubagentTaskRecord]) -> None:
        """Replace the stored records with ``records``."""
        ...
