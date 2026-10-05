"""Optional OS-level shell isolation backends (S4)."""

from __future__ import annotations

import shutil
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from newbot.domain.errors import ConfigLoadError, ToolError

_SEATBELT_PROFILE = """(version 1)
(allow default)
(deny file-write*)
(allow file-write* (subpath (param "WS")))
"""


class Sandbox(Protocol):
    """Wraps a shell invocation with OS-level isolation."""

    @property
    def name(self) -> str:
        """The operator-facing backend name."""
        ...

    def wrap(
        self, invocation: Sequence[str], *, workspace_root: Path
    ) -> Sequence[str]:
        """Return the argv to execute, or raise ``ToolError`` when unavailable."""
        ...


class NoSandbox:
    """Application guard only; no OS-level isolation."""

    name = "none"

    def wrap(
        self, invocation: Sequence[str], *, workspace_root: Path
    ) -> Sequence[str]:
        return tuple(invocation)


class BubblewrapSandbox:
    """Linux bubblewrap isolation: host read-only, workspace writable."""

    name = "bwrap"

    def __init__(self, executable: str) -> None:
        self._executable = executable

    def wrap(
        self, invocation: Sequence[str], *, workspace_root: Path
    ) -> Sequence[str]:
        root = str(workspace_root)
        return (
            self._executable,
            "--die-with-parent",
            "--ro-bind",
            "/",
            "/",
            "--bind",
            root,
            root,
            "--dev",
            "/dev",
            "--proc",
            "/proc",
            *invocation,
        )


class SeatbeltSandbox:
    """macOS seatbelt isolation: writes restricted to the workspace."""

    name = "seatbelt"

    def __init__(self, executable: str) -> None:
        self._executable = executable

    def wrap(
        self, invocation: Sequence[str], *, workspace_root: Path
    ) -> Sequence[str]:
        return (
            self._executable,
            "-D",
            f"WS={workspace_root}",
            "-p",
            _SEATBELT_PROFILE,
            *invocation,
        )


@dataclass(frozen=True, slots=True)
class UnavailableSandbox:
    """A configured backend without an executable; every command fails closed."""

    name: str

    def wrap(
        self, invocation: Sequence[str], *, workspace_root: Path
    ) -> Sequence[str]:
        raise ToolError(f"sandbox {self.name!r} is configured but not available")


@dataclass(frozen=True, slots=True)
class SandboxSelection:
    """The resolved sandbox backend plus an optional operator notice."""

    backend: Sandbox
    notice: str | None = None


def build_sandbox(name: str, *, platform: str | None = None) -> SandboxSelection:
    """Resolve a configured backend, falling back only where the docs allow."""
    host = sys.platform if platform is None else platform
    if name == "none":
        return SandboxSelection(NoSandbox())
    if name == "bwrap":
        if host != "linux":
            return SandboxSelection(NoSandbox(), _unsupported(name, "Linux"))
        executable = shutil.which("bwrap")
        if executable is None:
            return SandboxSelection(UnavailableSandbox(name))
        return SandboxSelection(BubblewrapSandbox(executable))
    if name == "seatbelt":
        if host != "darwin":
            return SandboxSelection(NoSandbox(), _unsupported(name, "macOS"))
        executable = shutil.which("sandbox-exec")
        if executable is None:
            return SandboxSelection(UnavailableSandbox(name))
        return SandboxSelection(SeatbeltSandbox(executable))
    raise ConfigLoadError(f"unknown sandbox {name!r}", location="tools.sandbox")


def _unsupported(name: str, target: str) -> str:
    return (
        f"sandbox {name!r} is only available on {target}; "
        "running with the application guard only"
    )
