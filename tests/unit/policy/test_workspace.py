"""Boundary tests for the workspace path guard (S1/S2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from newbot.domain.errors import PathAccessDenied
from newbot.policy.workspace import Capability, WorkspaceGuard


def test_relative_path_resolves_inside(tmp_path: Path) -> None:
    guard = WorkspaceGuard(tmp_path)

    assert guard.resolve("a/b.txt", Capability.READ) == (tmp_path / "a" / "b.txt").resolve()


def test_traversal_is_denied(tmp_path: Path) -> None:
    guard = WorkspaceGuard(tmp_path)

    with pytest.raises(PathAccessDenied):
        guard.resolve("../escape.txt", Capability.READ)


def test_absolute_path_outside_is_denied(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    guard = WorkspaceGuard(root)

    with pytest.raises(PathAccessDenied):
        guard.resolve(str(tmp_path / "secret.txt"), Capability.WRITE)


def test_absolute_path_inside_is_allowed(tmp_path: Path) -> None:
    guard = WorkspaceGuard(tmp_path)

    resolved = guard.resolve(str(tmp_path / "x.txt"), Capability.WRITE)

    assert resolved == (tmp_path / "x.txt").resolve()


def test_empty_path_is_denied(tmp_path: Path) -> None:
    with pytest.raises(PathAccessDenied):
        WorkspaceGuard(tmp_path).resolve("", Capability.READ)


def test_display_is_workspace_relative(tmp_path: Path) -> None:
    guard = WorkspaceGuard(tmp_path)

    assert guard.display(guard.resolve("a.txt", Capability.READ)) == "a.txt"


def test_read_root_allows_reads_only(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    extra = tmp_path / "knowledge"
    extra.mkdir()
    guard = WorkspaceGuard(root, read_roots=[extra])

    assert guard.resolve(str(extra / "doc.md"), Capability.READ) == (
        extra / "doc.md"
    ).resolve()
    with pytest.raises(PathAccessDenied):
        guard.resolve(str(extra / "doc.md"), Capability.WRITE)


def test_write_root_allows_writes_only(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    extra = tmp_path / "outbox"
    extra.mkdir()
    guard = WorkspaceGuard(root, write_roots=[extra])

    assert guard.resolve(str(extra / "out.txt"), Capability.WRITE) == (
        extra / "out.txt"
    ).resolve()
    with pytest.raises(PathAccessDenied):
        guard.resolve(str(extra / "out.txt"), Capability.READ)


def test_write_file_allowlist_is_exact(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    target = tmp_path / "etc" / "app.conf"
    target.parent.mkdir()
    guard = WorkspaceGuard(root, write_files=[target])

    assert guard.resolve(str(target), Capability.WRITE) == target.resolve()
    with pytest.raises(PathAccessDenied):
        guard.resolve(str(target.parent / "other.conf"), Capability.WRITE)
    with pytest.raises(PathAccessDenied):
        guard.resolve(str(target), Capability.READ)


def test_extra_root_traversal_is_denied(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    extra = tmp_path / "knowledge"
    extra.mkdir()
    guard = WorkspaceGuard(root, read_roots=[extra])

    with pytest.raises(PathAccessDenied):
        guard.resolve(str(extra / ".." / "secret.txt"), Capability.READ)
