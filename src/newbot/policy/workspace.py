"""Workspace path containment guard (S1/S2)."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from newbot.domain.errors import PathAccessDenied


class Capability(StrEnum):
    """The access a tool needs for a path."""

    READ = "read"
    WRITE = "write"


class WorkspaceGuard:
    """Resolves paths against a workspace root and enforces containment."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    @property
    def root(self) -> Path:
        """The resolved workspace root."""
        return self._root

    def resolve(self, raw: str, capability: Capability) -> Path:
        """Resolve ``raw`` inside the workspace, or raise ``PathAccessDenied``."""
        if not raw or "\x00" in raw:
            raise PathAccessDenied(f"{capability.value} denied: empty or invalid path")
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = self._root / candidate
        resolved = candidate.resolve()
        if not resolved.is_relative_to(self._root):
            raise PathAccessDenied(
                f"{capability.value} denied outside workspace: {raw!r}"
            )
        return resolved

    def display(self, path: Path) -> str:
        """Return a workspace-relative label for user-facing messages."""
        try:
            return str(path.relative_to(self._root)) or "."
        except ValueError:
            return path.name
