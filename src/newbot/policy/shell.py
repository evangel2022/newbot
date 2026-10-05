"""Application-level shell guard: working-dir containment and obvious escapes (S2)."""

from __future__ import annotations

import re
from pathlib import Path

from newbot.domain.errors import PathAccessDenied, ToolError
from newbot.policy.workspace import Capability, WorkspaceGuard

_TOKEN = re.compile(r"[^\s\"'`;|&()<>]+")


class ShellGuard:
    """Constrains shell commands to the workspace at the application level.

    This is not process isolation; it rejects commands whose working directory or
    obvious path arguments resolve outside the workspace.
    """

    def __init__(self, workspace: WorkspaceGuard) -> None:
        self._workspace = workspace

    @property
    def workspace_root(self) -> Path:
        """The resolved workspace root the guard enforces."""
        return self._workspace.root

    def working_dir(self, raw: str | None) -> Path:
        """Resolve a workspace-relative working directory, or raise."""
        path = self._workspace.resolve(raw or ".", Capability.READ)
        if not path.is_dir():
            raise PathAccessDenied(
                f"working directory is not a directory: {self._workspace.display(path)}"
            )
        return path

    def ensure_command_allowed(self, command: str) -> None:
        """Reject empty commands and obvious workspace escapes in path arguments."""
        if not command.strip() or "\x00" in command:
            raise ToolError("shell command must be a non-empty string")
        for token in _TOKEN.findall(command):
            candidate = token.rsplit("=", 1)[-1]
            if not _looks_like_path(candidate):
                continue
            if candidate.startswith("~"):
                raise ToolError(f"shell escape denied: home path {candidate!r}")
            try:
                self._workspace.resolve(candidate, Capability.READ)
            except PathAccessDenied as exc:
                raise ToolError(f"shell escape denied: {candidate!r}") from exc


def _looks_like_path(token: str) -> bool:
    return (
        "/" in token
        or "\\" in token
        or token.startswith("~")
        or token.startswith("..")
    )
