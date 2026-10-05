"""Guarded shell execution inside the workspace."""

from __future__ import annotations

import asyncio
import os
import shutil
import signal
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

from newbot.domain.errors import ToolError
from newbot.domain.tool import ToolSpec
from newbot.policy.redaction import bound_text
from newbot.policy.sandbox import NoSandbox, Sandbox
from newbot.policy.shell import ShellGuard
from newbot.ports.tools import ToolContext
from newbot.tools.base import ToolOutput, require_string

DEFAULT_TIMEOUT_SECONDS = 30.0
_MAX_OUTPUT_CHARS = 8_000

_SCHEMA: Mapping[str, object] = {
    "type": "object",
    "properties": {
        "command": {"type": "string", "description": "Shell command to run."},
        "working_dir": {
            "type": "string",
            "description": "Workspace-relative directory to run in (default: root).",
        },
    },
    "required": ["command"],
    "additionalProperties": False,
}


class ShellTool:
    """Runs one shell command with a workspace-contained working directory.

    Shell candidates are tried in preference order so that a PowerShell alias
    which cannot be launched falls back to the bundled Windows PowerShell.
    """

    def __init__(
        self,
        guard: ShellGuard,
        *,
        sandbox: Sandbox | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._guard = guard
        self._sandbox: Sandbox = NoSandbox() if sandbox is None else sandbox
        self._timeout = timeout_seconds
        self._candidates = _shell_candidates()
        self._argv: list[str] | None = None
        self.spec = ToolSpec(
            name="run_shell",
            description="Run a shell command inside the workspace and return its output.",
            parameters=_SCHEMA,
        )

    async def invoke(
        self, arguments: Mapping[str, object], ctx: ToolContext
    ) -> ToolOutput:
        command = require_string(arguments, "command")
        raw_dir = arguments.get("working_dir")
        if raw_dir is not None and not isinstance(raw_dir, str):
            raise ToolError("argument 'working_dir' must be a string")
        self._guard.ensure_command_allowed(command)
        cwd = self._guard.working_dir(raw_dir)
        process = await self._start(command, cwd)
        communicate = asyncio.ensure_future(process.communicate())
        done, _pending = await asyncio.wait({communicate}, timeout=self._timeout)
        if not done:
            await self._terminate(process)
            await communicate
            raise ToolError(
                f"shell command timed out after {self._timeout:g}s"
            )
        stdout, stderr = communicate.result()
        output = _combine(stdout, stderr)
        if process.returncode:
            return ToolOutput(
                text=f"exit code {process.returncode}\n{output}".strip(),
                is_error=True,
            )
        return ToolOutput(text=output or "(no output)")

    async def _start(
        self, command: str, cwd: Path
    ) -> asyncio.subprocess.Process:
        candidates = [self._argv] if self._argv else self._candidates
        failure: OSError | None = None
        for argv in candidates:
            invocation = self._sandbox.wrap(
                (*argv, command), workspace_root=self._guard.workspace_root
            )
            try:
                process = await asyncio.create_subprocess_exec(
                    *invocation,
                    cwd=str(cwd),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    start_new_session=sys.platform != "win32",
                )
            except OSError as exc:
                failure = exc
                continue
            self._argv = argv
            return process
        raise ToolError(f"no usable shell available: {failure}")

    @staticmethod
    async def _terminate(process: asyncio.subprocess.Process) -> None:
        if sys.platform == "win32":
            await asyncio.to_thread(_kill_tree, process.pid)
        else:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                process.kill()


def _shell_candidates() -> list[list[str]]:
    if sys.platform == "win32":
        candidates: list[list[str]] = []
        for name in ("pwsh", "powershell"):
            executable = shutil.which(name)
            if executable is not None:
                candidates.append(
                    [executable, "-NoProfile", "-NonInteractive", "-Command"]
                )
        return candidates
    shell = shutil.which("sh")
    return [[shell, "-c"]] if shell is not None else []


def _combine(stdout: bytes, stderr: bytes) -> str:
    parts = (
        stdout.decode("utf-8", errors="replace").strip(),
        stderr.decode("utf-8", errors="replace").strip(),
    )
    return bound_text("\n".join(part for part in parts if part), limit=_MAX_OUTPUT_CHARS)


def _kill_tree(pid: int) -> None:
    subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(pid)],
        capture_output=True,
        check=False,
    )
