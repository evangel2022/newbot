"""Sandbox selection and fail-closed availability tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from newbot.domain.errors import ConfigLoadError, ToolError
from newbot.policy.sandbox import (
    BubblewrapSandbox,
    NoSandbox,
    SeatbeltSandbox,
    UnavailableSandbox,
    build_sandbox,
)

ROOT = Path("/workspace")


def test_none_uses_the_application_guard_only() -> None:
    selection = build_sandbox("none")

    assert isinstance(selection.backend, NoSandbox)
    assert selection.notice is None
    assert selection.backend.wrap(["echo", "hi"], workspace_root=ROOT) == ("echo", "hi")


def test_unknown_backend_is_rejected() -> None:
    with pytest.raises(ConfigLoadError):
        build_sandbox("chroot")


def test_unix_backend_on_windows_falls_back_with_a_notice() -> None:
    selection = build_sandbox("bwrap", platform="win32")

    assert isinstance(selection.backend, NoSandbox)
    assert selection.notice is not None
    assert "bwrap" in selection.notice


def test_linux_backend_is_bubblewrap_or_fails_closed() -> None:
    selection = build_sandbox("bwrap", platform="linux")

    assert selection.notice is None
    assert isinstance(selection.backend, (BubblewrapSandbox, UnavailableSandbox))


def test_bwrap_binds_the_workspace_writable() -> None:
    invocation = BubblewrapSandbox("/usr/bin/bwrap").wrap(
        ["sh", "-c", "echo hi"], workspace_root=ROOT
    )

    assert invocation[0] == "/usr/bin/bwrap"
    assert "--ro-bind" in invocation
    bind = invocation.index("--bind")
    assert invocation[bind + 1 : bind + 3] == (str(ROOT), str(ROOT))
    assert invocation[-3:] == ("sh", "-c", "echo hi")


def test_seatbelt_restricts_writes_to_the_workspace() -> None:
    invocation = SeatbeltSandbox("/usr/bin/sandbox-exec").wrap(
        ["sh", "-c", "echo hi"], workspace_root=ROOT
    )

    assert invocation[0] == "/usr/bin/sandbox-exec"
    assert f"WS={ROOT}" in invocation
    profile = invocation[invocation.index("-p") + 1]
    assert "(deny file-write*)" in profile
    assert '(subpath (param "WS"))' in profile
    assert invocation[-3:] == ("sh", "-c", "echo hi")


def test_unavailable_backend_fails_closed() -> None:
    with pytest.raises(ToolError):
        UnavailableSandbox("bwrap").wrap(["sh"], workspace_root=ROOT)
