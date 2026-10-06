"""Guarded application of unified diffs to workspace text files."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from newbot.domain.errors import ToolError
from newbot.domain.tool import ToolSpec
from newbot.policy.workspace import Capability, WorkspaceGuard
from newbot.ports.tools import ToolContext
from newbot.tools.base import ToolOutput, require_string

_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

_SCHEMA: Mapping[str, object] = {
    "type": "object",
    "properties": {
        "patch": {
            "type": "string",
            "description": "Unified diff modifying existing workspace text files.",
        }
    },
    "required": ["patch"],
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class _Hunk:
    old_lines: tuple[str, ...]
    new_lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _FilePatch:
    path: str
    hunks: tuple[_Hunk, ...]


class ApplyPatchTool:
    """Applies a unified diff to existing workspace text files.

    Every hunk must match its file's current text uniquely, and the whole patch
    is planned before anything is written, so a bad hunk leaves every file
    untouched. File creation and deletion are out of scope (use ``write_file``).
    """

    def __init__(self, guard: WorkspaceGuard) -> None:
        self._guard = guard
        self.spec = ToolSpec(
            name="apply_patch",
            description=(
                "Apply a unified diff to existing workspace text files. Each hunk "
                "must match its file uniquely; creating or deleting files is not "
                "supported (use write_file)."
            ),
            parameters=_SCHEMA,
        )

    async def invoke(
        self, arguments: Mapping[str, object], ctx: ToolContext
    ) -> ToolOutput:
        file_patches = _parse(require_string(arguments, "patch"))
        plans: list[tuple[Path, str]] = []
        hunk_total = 0
        for file_patch in file_patches:
            path = self._guard.resolve(file_patch.path, Capability.WRITE)
            display = self._guard.display(path)
            if not path.is_file():
                raise ToolError(f"not a file: {display}")
            updated = await asyncio.to_thread(_plan_file, path, file_patch, display)
            plans.append((path, updated))
            hunk_total += len(file_patch.hunks)

        def _commit() -> None:
            for path, content in plans:
                path.write_bytes(content.encode("utf-8"))

        try:
            await asyncio.to_thread(_commit)
        except OSError as exc:
            raise ToolError(f"cannot apply patch: {exc}") from exc
        return ToolOutput(text=f"applied {hunk_total} hunk(s) to {len(plans)} file(s)")


def _plan_file(path: Path, file_patch: _FilePatch, display: str) -> str:
    try:
        raw = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ToolError(f"cannot patch {display}: not a UTF-8 text file") from exc
    ending = "\r\n" if "\r\n" in raw else "\n"
    logical = raw.replace("\r\n", "\n").replace("\r", "\n")
    trailing = logical.endswith("\n")
    lines = logical.splitlines()
    for hunk in file_patch.hunks:
        positions = _match_positions(lines, hunk.old_lines)
        if not positions:
            raise ToolError(f"{display}: a patch hunk did not match")
        if len(positions) > 1:
            raise ToolError(
                f"{display}: a patch hunk matches {len(positions)} times; "
                "include more context"
            )
        start = positions[0]
        lines[start : start + len(hunk.old_lines)] = list(hunk.new_lines)
    updated = "\n".join(lines)
    if trailing:
        updated += "\n"
    if ending != "\n":
        updated = updated.replace("\n", ending)
    return updated


def _match_positions(lines: Sequence[str], needle: Sequence[str]) -> list[int]:
    size = len(needle)
    wanted = list(needle)
    return [
        index
        for index in range(len(lines) - size + 1)
        if list(lines[index : index + size]) == wanted
    ]


def _parse(patch: str) -> tuple[_FilePatch, ...]:
    lines = patch.splitlines()
    index = 0
    files: list[_FilePatch] = []
    while index < len(lines):
        if not lines[index].startswith("--- "):
            index += 1
            continue
        old_path = _clean_path(lines[index][4:])
        index += 1
        if index >= len(lines) or not lines[index].startswith("+++ "):
            raise ToolError("patch is malformed: '---' without '+++'")
        new_path = _clean_path(lines[index][4:])
        index += 1
        if old_path != new_path:
            raise ToolError(f"renaming {old_path!r} to {new_path!r} is not supported")
        hunks: list[_Hunk] = []
        while index < len(lines) and lines[index].startswith("@@"):
            hunk, index = _parse_hunk(lines, index)
            hunks.append(hunk)
        if not hunks:
            raise ToolError(f"patch for {new_path!r} has no hunks")
        files.append(_FilePatch(path=new_path, hunks=tuple(hunks)))
    if not files:
        raise ToolError("patch contains no file sections")
    return tuple(files)


def _parse_hunk(lines: Sequence[str], index: int) -> tuple[_Hunk, int]:
    match = _HUNK_HEADER.match(lines[index])
    if match is None:
        raise ToolError(f"patch has a malformed hunk header: {lines[index]!r}")
    old_count = int(match.group(2)) if match.group(2) else 1
    new_count = int(match.group(4)) if match.group(4) else 1
    index += 1
    old_lines: list[str] = []
    new_lines: list[str] = []
    while len(old_lines) < old_count or len(new_lines) < new_count:
        if index >= len(lines):
            raise ToolError("patch hunk is truncated")
        line = lines[index]
        index += 1
        if line.startswith("\\"):
            raise ToolError("patches without a trailing newline are not supported")
        prefix = line[:1]
        if prefix == " ":
            old_lines.append(line[1:])
            new_lines.append(line[1:])
        elif prefix == "-":
            old_lines.append(line[1:])
        elif prefix == "+":
            new_lines.append(line[1:])
        else:
            raise ToolError(f"unsupported patch line: {line!r}")
    return _Hunk(tuple(old_lines), tuple(new_lines)), index


def _clean_path(raw: str) -> str:
    path = raw.split("\t", 1)[0].strip()
    if path == "/dev/null":
        raise ToolError("creating or deleting files is not supported; use write_file")
    if path.startswith(("a/", "b/")):
        path = path[2:]
    if not path:
        raise ToolError("patch has an empty file path")
    return path
