"""The durable-file versioning interface."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from newbot.domain.version import FileVersion


class VersioningPort(Protocol):
    """Writes durable files while keeping every state inspectable and restorable."""

    async def write(self, path: Path, content: str) -> str:
        """Write ``content`` to ``path`` and record it as a version."""
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
