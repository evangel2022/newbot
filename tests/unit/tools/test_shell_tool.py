"""Contract tests for the guarded shell tool."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from newbot.domain.errors import ToolError
from newbot.domain.session import SessionKey
from newbot.domain.tool import ToolCall
from newbot.policy.shell import ShellGuard
from newbot.policy.workspace import WorkspaceGuard
from newbot.ports.tools import ToolContext
from newbot.tools.registry import ToolRegistry
from newbot.tools.shell import ShellTool


def _ctx(root: Path) -> ToolContext:
    return ToolContext(session=SessionKey("t", "c"), workspace_root=root)


def _registry(root: Path, *, timeout: float = 30.0) -> ToolRegistry:
    return ToolRegistry(
        [ShellTool(ShellGuard(WorkspaceGuard(root)), timeout_seconds=timeout)]
    )


class _RewriteSandbox:
    name = "rewrite"

    def __init__(self, argv: list[str]) -> None:
        self._argv = argv
        self.seen: tuple[tuple[str, ...], Path] | None = None

    def wrap(
        self, invocation: tuple[str, ...], *, workspace_root: Path
    ) -> list[str]:
        self.seen = (tuple(invocation), workspace_root)
        return self._argv


class _DenySandbox:
    name = "deny"

    def wrap(
        self, invocation: tuple[str, ...], *, workspace_root: Path
    ) -> list[str]:
        raise ToolError("sandbox unavailable")


def _call(command: str, **extra: object) -> ToolCall:
    arguments = json.dumps({"command": command, **extra})
    return ToolCall(id="c1", name="run_shell", arguments=arguments)


async def test_runs_a_command_in_the_workspace(tmp_path: Path) -> None:
    result = await _registry(tmp_path).invoke(
        _call('python -c "import os; print(os.getcwd())"'), _ctx(tmp_path)
    )

    assert result.is_error is False
    assert Path(result.content.strip()) == tmp_path.resolve()


async def test_working_dir_selects_a_subdirectory(tmp_path: Path) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()

    result = await _registry(tmp_path).invoke(
        _call('python -c "import os; print(os.getcwd())"', working_dir="sub"),
        _ctx(tmp_path),
    )

    assert Path(result.content.strip()) == sub.resolve()


async def test_nonzero_exit_becomes_an_error_result(tmp_path: Path) -> None:
    result = await _registry(tmp_path).invoke(_call("exit 3"), _ctx(tmp_path))

    assert result.is_error is True
    assert "exit code 3" in result.content


async def test_timeout_becomes_an_error_result(tmp_path: Path) -> None:
    result = await _registry(tmp_path, timeout=0.2).invoke(
        _call('python -c "import time; time.sleep(1)"'), _ctx(tmp_path)
    )

    assert result.is_error is True
    assert "timed out" in result.content


async def test_workspace_escape_is_denied(tmp_path: Path) -> None:
    result = await _registry(tmp_path).invoke(_call("cd .."), _ctx(tmp_path))

    assert result.is_error is True
    assert "denied" in result.content


async def test_sandbox_wraps_the_invocation(tmp_path: Path) -> None:
    sandbox = _RewriteSandbox([sys.executable, "-c", "print('sandboxed')"])
    tool = ShellTool(ShellGuard(WorkspaceGuard(tmp_path)), sandbox=sandbox)

    result = await ToolRegistry([tool]).invoke(_call("echo ignored"), _ctx(tmp_path))

    assert result.is_error is False
    assert result.content == "sandboxed"
    assert sandbox.seen is not None
    invocation, root = sandbox.seen
    assert root == tmp_path.resolve()
    assert invocation[-1] == "echo ignored"


async def test_unavailable_sandbox_fails_closed(tmp_path: Path) -> None:
    tool = ShellTool(ShellGuard(WorkspaceGuard(tmp_path)), sandbox=_DenySandbox())
    command = "python -c \"open('ran.txt','w').write('x')\""

    result = await ToolRegistry([tool]).invoke(_call(command), _ctx(tmp_path))

    assert result.is_error is True
    assert "sandbox" in result.content
    assert not (tmp_path / "ran.txt").exists()
