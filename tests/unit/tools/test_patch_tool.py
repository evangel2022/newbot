"""Boundary tests for the guarded unified-diff patch tool."""

from __future__ import annotations

import json
from pathlib import Path

from newbot.domain.session import SessionKey
from newbot.domain.tool import ToolCall
from newbot.policy.network import NetworkGuard
from newbot.policy.workspace import WorkspaceGuard
from newbot.ports.tools import ToolContext
from newbot.tools.registry import ToolRegistry, build_default_registry


def _ctx() -> ToolContext:
    return ToolContext(session=SessionKey("t", "c"), workspace_root=Path("."))


def _call(**arguments: object) -> ToolCall:
    return ToolCall(id="c1", name="apply_patch", arguments=json.dumps(arguments))


def _registry(guard: WorkspaceGuard) -> ToolRegistry:
    return build_default_registry(guard, network_guard=NetworkGuard())


async def test_applies_a_single_hunk(tmp_path: Path) -> None:
    (tmp_path / "note.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
    registry = _registry(WorkspaceGuard(tmp_path))
    patch = (
        "--- a/note.txt\n"
        "+++ b/note.txt\n"
        "@@ -1,3 +1,3 @@\n"
        " one\n"
        "-two\n"
        "+TWO\n"
        " three\n"
    )

    result = await registry.invoke(_call(patch=patch), _ctx())

    assert result.is_error is False
    assert result.content == "applied 1 hunk(s) to 1 file(s)"
    assert (tmp_path / "note.txt").read_text(encoding="utf-8") == "one\nTWO\nthree\n"


async def test_applies_multiple_hunks_to_one_file(tmp_path: Path) -> None:
    (tmp_path / "f.txt").write_text("a\nb\nc\nd\ne\n", encoding="utf-8")
    registry = _registry(WorkspaceGuard(tmp_path))
    patch = (
        "--- a/f.txt\n"
        "+++ b/f.txt\n"
        "@@ -1,2 +1,2 @@\n"
        " a\n"
        "-b\n"
        "+B\n"
        "@@ -4,2 +4,2 @@\n"
        " d\n"
        "-e\n"
        "+E\n"
    )

    result = await registry.invoke(_call(patch=patch), _ctx())

    assert result.is_error is False
    assert (tmp_path / "f.txt").read_text(encoding="utf-8") == "a\nB\nc\nd\nE\n"


async def test_applies_a_patch_across_multiple_files(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b\n", encoding="utf-8")
    registry = _registry(WorkspaceGuard(tmp_path))
    patch = (
        "--- a/a.txt\n"
        "+++ b/a.txt\n"
        "@@ -1,1 +1,1 @@\n"
        "-a\n"
        "+A\n"
        "--- a/b.txt\n"
        "+++ b/b.txt\n"
        "@@ -1,1 +1,1 @@\n"
        "-b\n"
        "+B\n"
    )

    result = await registry.invoke(_call(patch=patch), _ctx())

    assert result.is_error is False
    assert result.content == "applied 2 hunk(s) to 2 file(s)"
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "A\n"
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "B\n"


async def test_a_missing_hunk_leaves_the_file_untouched(tmp_path: Path) -> None:
    (tmp_path / "note.txt").write_text("hello\n", encoding="utf-8")
    registry = _registry(WorkspaceGuard(tmp_path))
    patch = (
        "--- a/note.txt\n"
        "+++ b/note.txt\n"
        "@@ -1,1 +1,1 @@\n"
        "-absent\n"
        "+present\n"
    )

    result = await registry.invoke(_call(patch=patch), _ctx())

    assert result.is_error is True
    assert "did not match" in result.content
    assert (tmp_path / "note.txt").read_text(encoding="utf-8") == "hello\n"


async def test_an_ambiguous_hunk_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "note.txt").write_text("x\nx\n", encoding="utf-8")
    registry = _registry(WorkspaceGuard(tmp_path))
    patch = (
        "--- a/note.txt\n"
        "+++ b/note.txt\n"
        "@@ -1,1 +1,1 @@\n"
        "-x\n"
        "+y\n"
    )

    result = await registry.invoke(_call(patch=patch), _ctx())

    assert result.is_error is True
    assert "2 times" in result.content
    assert (tmp_path / "note.txt").read_text(encoding="utf-8") == "x\nx\n"


async def test_a_bad_hunk_leaves_earlier_files_untouched(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b\n", encoding="utf-8")
    registry = _registry(WorkspaceGuard(tmp_path))
    patch = (
        "--- a/a.txt\n"
        "+++ b/a.txt\n"
        "@@ -1,1 +1,1 @@\n"
        "-a\n"
        "+A\n"
        "--- a/b.txt\n"
        "+++ b/b.txt\n"
        "@@ -1,1 +1,1 @@\n"
        "-absent\n"
        "+B\n"
    )

    result = await registry.invoke(_call(patch=patch), _ctx())

    assert result.is_error is True
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "a\n"
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "b\n"


async def test_a_path_outside_the_workspace_is_denied(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")
    registry = _registry(WorkspaceGuard(root))
    patch = (
        "--- a/../outside.txt\n"
        "+++ b/../outside.txt\n"
        "@@ -1,1 +1,1 @@\n"
        "-secret\n"
        "+leaked\n"
    )

    result = await registry.invoke(_call(patch=patch), _ctx())

    assert result.is_error is True
    assert outside.read_text(encoding="utf-8") == "secret\n"


async def test_creating_or_deleting_a_file_is_rejected(tmp_path: Path) -> None:
    registry = _registry(WorkspaceGuard(tmp_path))
    patch = (
        "--- a/new.txt\n"
        "+++ /dev/null\n"
        "@@ -1,1 +0,0 @@\n"
        "-gone\n"
    )

    result = await registry.invoke(_call(patch=patch), _ctx())

    assert result.is_error is True
    assert "not supported" in result.content
    assert not (tmp_path / "new.txt").exists()


async def test_crlf_line_endings_are_preserved(tmp_path: Path) -> None:
    target = tmp_path / "note.txt"
    target.write_bytes(b"one\r\ntwo\r\n")
    registry = _registry(WorkspaceGuard(tmp_path))
    patch = (
        "--- a/note.txt\n"
        "+++ b/note.txt\n"
        "@@ -1,2 +1,2 @@\n"
        " one\n"
        "-two\n"
        "+TWO\n"
    )

    result = await registry.invoke(_call(patch=patch), _ctx())

    assert result.is_error is False
    assert target.read_bytes() == b"one\r\nTWO\r\n"


async def test_a_missing_trailing_newline_is_preserved(tmp_path: Path) -> None:
    target = tmp_path / "note.txt"
    target.write_text("a\nb", encoding="utf-8")
    registry = _registry(WorkspaceGuard(tmp_path))
    patch = (
        "--- a/note.txt\n"
        "+++ b/note.txt\n"
        "@@ -1,2 +1,2 @@\n"
        " a\n"
        "-b\n"
        "+B\n"
    )

    result = await registry.invoke(_call(patch=patch), _ctx())

    assert result.is_error is False
    assert target.read_text(encoding="utf-8") == "a\nB"


async def test_a_patch_without_file_sections_is_rejected(tmp_path: Path) -> None:
    registry = _registry(WorkspaceGuard(tmp_path))

    result = await registry.invoke(_call(patch="not a diff\n"), _ctx())

    assert result.is_error is True
    assert "no file sections" in result.content


async def test_a_rename_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "old.txt").write_text("x\n", encoding="utf-8")
    registry = _registry(WorkspaceGuard(tmp_path))
    patch = (
        "--- a/old.txt\n"
        "+++ b/new.txt\n"
        "@@ -1,1 +1,1 @@\n"
        "-x\n"
        "+y\n"
    )

    result = await registry.invoke(_call(patch=patch), _ctx())

    assert result.is_error is True
    assert "renaming" in result.content
    assert (tmp_path / "old.txt").read_text(encoding="utf-8") == "x\n"
    assert not (tmp_path / "new.txt").exists()
