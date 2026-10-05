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
