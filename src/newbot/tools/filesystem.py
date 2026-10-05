"""Guarded workspace filesystem tools."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from newbot.domain.errors import ToolError
from newbot.domain.tool import ToolSpec
from newbot.policy.workspace import Capability, WorkspaceGuard
from newbot.ports.tools import ToolContext
from newbot.tools.base import ToolOutput, require_string

_MAX_READ_CHARS = 100_000

_PATH_PROPERTY: Mapping[str, object] = {
    "type": "string",
    "description": "Path relative to the workspace root.",
}

_READ_SCHEMA: Mapping[str, object] = {
    "type": "object",
    "properties": {"path": _PATH_PROPERTY},
    "required": ["path"],
    "additionalProperties": False,
}

_WRITE_SCHEMA: Mapping[str, object] = {
    "type": "object",
    "properties": {
        "path": _PATH_PROPERTY,
        "content": {"type": "string", "description": "Full file contents to write."},
    },
    "required": ["path", "content"],
    "additionalProperties": False,
}

_LIST_SCHEMA: Mapping[str, object] = {
    "type": "object",
    "properties": {"path": _PATH_PROPERTY},
    "required": [],
    "additionalProperties": False,
}


class ReadFileTool:
    """Reads a UTF-8 text file inside the workspace."""

    def __init__(self, guard: WorkspaceGuard) -> None:
        self._guard = guard
        self.spec = ToolSpec(
            name="read_file",
            description="Read a UTF-8 text file from the workspace.",
            parameters=_READ_SCHEMA,
        )

    async def invoke(
        self, arguments: Mapping[str, object], ctx: ToolContext
    ) -> ToolOutput:
        path = self._guard.resolve(require_string(arguments, "path"), Capability.READ)
        if not path.is_file():
            raise ToolError(f"not a file: {self._guard.display(path)}")

        def _read() -> str:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                return handle.read(_MAX_READ_CHARS)

        try:
            return ToolOutput(text=await asyncio.to_thread(_read))
        except OSError as exc:
            raise ToolError(f"cannot read {self._guard.display(path)}: {exc}") from exc


class WriteFileTool:
    """Writes a UTF-8 text file inside the workspace."""

    def __init__(self, guard: WorkspaceGuard) -> None:
        self._guard = guard
        self.spec = ToolSpec(
            name="write_file",
            description="Write a UTF-8 text file in the workspace, creating parents.",
            parameters=_WRITE_SCHEMA,
        )

    async def invoke(
        self, arguments: Mapping[str, object], ctx: ToolContext
    ) -> ToolOutput:
        path = self._guard.resolve(require_string(arguments, "path"), Capability.WRITE)
        content = arguments.get("content")
        if not isinstance(content, str):
            raise ToolError("argument 'content' must be a string")

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

        try:
            await asyncio.to_thread(_write)
        except OSError as exc:
            raise ToolError(f"cannot write {self._guard.display(path)}: {exc}") from exc
        return ToolOutput(text=f"wrote {len(content)} chars to {self._guard.display(path)}")


class ListDirTool:
    """Lists directory entries inside the workspace."""

    def __init__(self, guard: WorkspaceGuard) -> None:
        self._guard = guard
        self.spec = ToolSpec(
            name="list_dir",
            description="List entries of a workspace directory (defaults to the root).",
            parameters=_LIST_SCHEMA,
        )

    async def invoke(
        self, arguments: Mapping[str, object], ctx: ToolContext
    ) -> ToolOutput:
        raw = arguments.get("path", ".")
        if not isinstance(raw, str):
            raise ToolError("argument 'path' must be a string")
        path = self._guard.resolve(raw or ".", Capability.READ)
        if not path.is_dir():
            raise ToolError(f"not a directory: {self._guard.display(path)}")

        def _list() -> list[str]:
            return sorted(
                f"{entry.name}/" if entry.is_dir() else entry.name
                for entry in path.iterdir()
            )

        try:
            entries = await asyncio.to_thread(_list)
        except OSError as exc:
            raise ToolError(f"cannot list {self._guard.display(path)}: {exc}") from exc
        return ToolOutput(text="\n".join(entries) if entries else "(empty)")
