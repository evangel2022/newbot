"""Workspace path containment guard (S1/S2)."""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path

from newbot.domain.errors import PathAccessDenied


class Capability(StrEnum):
    """The access a tool needs for a path."""

    READ = "read"
    WRITE = "write"


class WorkspaceGuard:
    """Resolves paths against a workspace root and its capability-specific roots.

    A read root grants reads only; a write root grants writes only; a write file
    grants writes to that exact file only. None of them implies the other.
    """

    def __init__(
        self,
        root: Path,
        *,
        read_roots: Sequence[Path] = (),
        write_roots: Sequence[Path] = (),
        write_files: Sequence[Path] = (),
    ) -> None:
        self._root = root.resolve()
        self._read_roots = tuple(path.resolve() for path in read_roots)
        self._write_roots = tuple(path.resolve() for path in write_roots)
        self._write_files = tuple(path.resolve() for path in write_files)

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
        if self._permitted(resolved, capability):
            return resolved
        raise PathAccessDenied(
            f"{capability.value} denied outside permitted paths: {raw!r}"
        )

    def _permitted(self, path: Path, capability: Capability) -> bool:
        if path.is_relative_to(self._root):
            return True
        if capability is Capability.READ:
            return any(path.is_relative_to(root) for root in self._read_roots)
        return path in self._write_files or any(
            path.is_relative_to(root) for root in self._write_roots
        )

    def display(self, path: Path) -> str:
        """Return a workspace-relative label for user-facing messages."""
        try:
            return str(path.relative_to(self._root)) or "."
        except ValueError:
            return path.name
