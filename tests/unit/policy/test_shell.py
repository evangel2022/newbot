"""Boundary tests for the application-level shell guard."""

from __future__ import annotations

from pathlib import Path

import pytest

from newbot.domain.errors import PathAccessDenied, ToolError
from newbot.policy.shell import ShellGuard
from newbot.policy.workspace import WorkspaceGuard


def _guard(tmp_path: Path) -> ShellGuard:
    return ShellGuard(WorkspaceGuard(tmp_path))


def test_working_dir_outside_the_workspace_is_denied(tmp_path: Path) -> None:
    with pytest.raises(PathAccessDenied):
        _guard(tmp_path).working_dir("..")


def test_working_dir_inside_the_workspace_is_resolved(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()

    assert _guard(tmp_path).working_dir("sub") == (tmp_path / "sub").resolve()
    assert _guard(tmp_path).working_dir(None) == tmp_path.resolve()


def test_working_dir_must_be_a_directory(tmp_path: Path) -> None:
    with pytest.raises(PathAccessDenied):
        _guard(tmp_path).working_dir("missing")


def test_absolute_path_argument_outside_the_workspace_is_denied(
    tmp_path: Path,
) -> None:
    outside = tmp_path.parent / "secret.txt"

    with pytest.raises(ToolError):
        _guard(tmp_path).ensure_command_allowed(f"cat {outside}")


def test_parent_traversal_argument_is_denied(tmp_path: Path) -> None:
    with pytest.raises(ToolError):
        _guard(tmp_path).ensure_command_allowed("cd ..")


def test_in_workspace_and_plain_commands_are_allowed(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    guard = _guard(tmp_path)

    guard.ensure_command_allowed("echo hello")
    guard.ensure_command_allowed("python -c 'print(1)'")
    guard.ensure_command_allowed("cat sub/note.txt")


def test_empty_or_nul_command_is_rejected(tmp_path: Path) -> None:
    guard = _guard(tmp_path)

    with pytest.raises(ToolError):
        guard.ensure_command_allowed("   ")
    with pytest.raises(ToolError):
        guard.ensure_command_allowed("echo \x00 hi")
