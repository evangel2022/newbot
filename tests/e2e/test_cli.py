"""CLI surface tests: in-process streaming and subprocess exit codes."""

from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

from newbot.cli.entry import main
from newbot.domain.message import Message, Role
from newbot.domain.tool import ToolCall
from support import FakeProvider, ScriptedProvider, reply_events

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"

CONFIG = """
[provider]
baseUrl = "https://api.example.com/v1"
apiKey = "k"

[agent]
model = "gpt-test"
"""


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    return subprocess.run(
        [sys.executable, "-m", "newbot", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def _write_config(tmp_path: Path) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(
        CONFIG + f'\n[sessions]\ndir = "{(tmp_path / "sessions").as_posix()}"\n',
        encoding="utf-8",
    )
    return path


def test_cli_run_streams_reply(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _write_config(tmp_path)

    code = main(
        ["run", "-m", "hello", "--config", str(config)],
        provider_factory=lambda _settings: FakeProvider(reply_events("Hi from fake")),
    )

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == "Hi from fake\n"


def test_cli_help_exits_zero() -> None:
    result = _run_cli("--help")

    assert result.returncode == 0
    assert "usage" in result.stdout


def test_cli_missing_config_exits_two(tmp_path: Path) -> None:
    result = _run_cli("run", "-m", "hi", "--config", str(tmp_path / "nope.toml"))

    assert result.returncode == 2
    assert "error:" in result.stderr


def test_cli_empty_message_exits_two(tmp_path: Path) -> None:
    result = _run_cli("run", "-m", "   ", "--config", str(_write_config(tmp_path)))

    assert result.returncode == 2
    assert "must not be empty" in result.stderr


def test_cli_runs_a_tool_end_to_end(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "note.txt").write_text("payload-42", encoding="utf-8")
    config = tmp_path / "config.toml"
    config.write_text(
        "[provider]\n"
        'baseUrl = "https://api.example.com/v1"\n'
        'apiKey = "k"\n\n'
        "[agent]\n"
        'model = "stub"\n'
        f'workspace = "{workspace.as_posix()}"\n\n'
        "[sessions]\n"
        f'dir = "{(tmp_path / "sessions").as_posix()}"\n',
        encoding="utf-8",
    )
    provider = ScriptedProvider(
        [
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=(
                    ToolCall(id="c1", name="read_file", arguments='{"path":"note.txt"}'),
                ),
            ),
            Message(role=Role.ASSISTANT, content="The note says payload-42"),
        ]
    )

    code = main(
        ["run", "-m", "read the note", "--config", str(config)],
        provider_factory=lambda _settings: provider,
    )

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == "The note says payload-42\n"


def test_cli_interactive_runs_a_turn_per_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _write_config(tmp_path)
    provider = ScriptedProvider(
        [
            Message(role=Role.ASSISTANT, content="first reply"),
            Message(role=Role.ASSISTANT, content="second reply"),
        ]
    )

    code = main(
        ["--config", str(config)],
        provider_factory=lambda _settings: provider,
        stdin=io.StringIO("first question\nsecond question\n"),
    )

    captured = capsys.readouterr()
    assert code == 0
    assert "first reply" in captured.out
    assert "second reply" in captured.out
    assert [message.content for message in provider.requests[1].messages] == [
        "first question",
        "first reply",
        "second question",
    ]


def test_cli_interactive_exit_command_stops_without_a_turn(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    provider = FakeProvider(reply_events("unused"))

    code = main(
        ["--config", str(config)],
        provider_factory=lambda _settings: provider,
        stdin=io.StringIO("/exit\n"),
    )

    assert code == 0
    assert provider.requests == []


class _InterruptingStdin:
    def readline(self) -> str:
        raise KeyboardInterrupt


def test_cli_interactive_keyboard_interrupt_exits_130(tmp_path: Path) -> None:
    config = _write_config(tmp_path)

    code = main(
        ["--config", str(config)],
        provider_factory=lambda _settings: FakeProvider(reply_events("unused")),
        stdin=_InterruptingStdin(),
    )

    assert code == 130
