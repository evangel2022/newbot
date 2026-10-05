"""The durable-file versioning interface."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from newbot.domain.version import FileVersion


class VersioningPort(Protocol):
    """Writes durable files while keeping every state inspectable and restorable."""

    async def write(self, path: Path, content: str) -> str:
        """Write ``content`` to ``path`` and record it as a version."""
        ...

    async def write_set(self, files: Sequence[tuple[Path, str]]) -> str:
        """Write several files as one change-set; return the change-set id.

        Grouping lets the operator revert a whole curation pass at once instead
        of restoring its files one by one.
        """
        ...

    async def versions(self) -> tuple[FileVersion, ...]:
        """Return every recorded version, newest first."""
        ...

    async def history(self, path: Path) -> tuple[FileVersion, ...]:
        """Return the recorded versions of ``path``, newest first."""
        ...

    async def read(self, path: Path, version_id: str) -> str:
        """Return the recorded content of one version of ``path``."""
        ...

    async def restore(self, path: Path, version_id: str) -> None:
        """Write a recorded version back to ``path`` as its newest version."""
        ...

    async def revert_set(self, change_set_id: str) -> tuple[str, ...]:
        """Undo one change-set; return the paths it touched, in order.

        Each file returns to the version that preceded the change-set, and a
        file the change-set created is removed again.
        """
        ...
