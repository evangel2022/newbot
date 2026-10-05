"""Boundary tests for the guarded filesystem tools."""

from __future__ import annotations

import json
from collections.abc import Collection
from pathlib import Path

from newbot.domain.session import SessionKey
from newbot.domain.tool import ToolCall
from newbot.policy.network import NetworkGuard
from newbot.policy.workspace import WorkspaceGuard
from newbot.ports.tools import ToolContext
from newbot.tools.registry import ToolRegistry, build_default_registry


def _ctx() -> ToolContext:
    return ToolContext(session=SessionKey("t", "c"), workspace_root=Path("."))


def _call(name: str, **arguments: object) -> ToolCall:
    return ToolCall(id="c1", name=name, arguments=json.dumps(arguments))


def _registry(
    guard: WorkspaceGuard, *, allowlist: Collection[str] | None = None
) -> ToolRegistry:
    return build_default_registry(
        guard, network_guard=NetworkGuard(), allowlist=allowlist
    )


async def test_read_file_returns_contents(tmp_path: Path) -> None:
    (tmp_path / "note.txt").write_text("hello", encoding="utf-8")
    registry = _registry(WorkspaceGuard(tmp_path))

    result = await registry.invoke(_call("read_file", path="note.txt"), _ctx())

    assert result.is_error is False
    assert result.content == "hello"


async def test_read_file_traversal_is_denied(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    root = tmp_path / "ws"
    root.mkdir()
    registry = _registry(WorkspaceGuard(root))

    result = await registry.invoke(_call("read_file", path="../outside.txt"), _ctx())

    assert result.is_error is True
    assert "denied" in result.content
    assert "secret" not in result.content


async def test_write_file_creates_file_inside_workspace(tmp_path: Path) -> None:
    registry = _registry(WorkspaceGuard(tmp_path))

    result = await registry.invoke(
        _call("write_file", path="sub/out.txt", content="data"), _ctx()
    )

    assert result.is_error is False
    assert (tmp_path / "sub" / "out.txt").read_text(encoding="utf-8") == "data"


async def test_write_file_outside_workspace_is_denied(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    escape = tmp_path / "escape.txt"
    registry = _registry(WorkspaceGuard(root))

    result = await registry.invoke(
        _call("write_file", path=str(escape), content="x"), _ctx()
    )

    assert result.is_error is True
    assert not escape.exists()


async def test_list_dir_lists_sorted_entries(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    registry = _registry(WorkspaceGuard(tmp_path))

    result = await registry.invoke(_call("list_dir"), _ctx())

    assert result.content.splitlines() == ["a.txt", "sub/"]


async def test_allowlist_disables_write_file(tmp_path: Path) -> None:
    registry = _registry(WorkspaceGuard(tmp_path), allowlist={"read_file"})

    result = await registry.invoke(
        _call("write_file", path="x.txt", content="x"), _ctx()
    )

    assert result.is_error is True
    assert "unknown tool" in result.content


async def test_extra_read_root_is_readable_but_not_writable(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    extra = tmp_path / "knowledge"
    extra.mkdir()
    (extra / "doc.md").write_text("reference", encoding="utf-8")
    registry = _registry(WorkspaceGuard(root, read_roots=[extra]))

    read = await registry.invoke(_call("read_file", path=str(extra / "doc.md")), _ctx())
    write = await registry.invoke(
        _call("write_file", path=str(extra / "new.md"), content="x"), _ctx()
    )

    assert read.content == "reference"
    assert write.is_error is True
    assert not (extra / "new.md").exists()


async def test_extra_write_root_is_writable_but_not_readable(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    extra = tmp_path / "outbox"
    extra.mkdir()
    (extra / "existing.txt").write_text("data", encoding="utf-8")
    registry = _registry(WorkspaceGuard(root, write_roots=[extra]))

    write = await registry.invoke(
        _call("write_file", path=str(extra / "new.txt"), content="x"), _ctx()
    )
    read = await registry.invoke(
        _call("read_file", path=str(extra / "existing.txt")), _ctx()
    )

    assert write.is_error is False
    assert (extra / "new.txt").read_text(encoding="utf-8") == "x"
    assert read.is_error is True
