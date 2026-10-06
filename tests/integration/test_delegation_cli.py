"""End-to-end delegation through the CLI: a parent delegates and waits."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from newbot.cli.entry import main
from newbot.domain.message import Message, Role
from newbot.domain.provider import Completed, ModelRequest, StreamEvent, TextDelta
from newbot.domain.tool import ToolCall
from support import ScriptedProvider

CONFIG = """
[provider]
baseUrl = "https://api.example.com/v1"
apiKey = "k"

[agent]
model = "gpt-test"
"""


def _write_config(tmp_path: Path) -> Path:
    workspace = tmp_path / "ws"
    workspace.mkdir(exist_ok=True)
    path = tmp_path / "config.toml"
    path.write_text(
        CONFIG
        + f'workspace = "{workspace.as_posix()}"\n'
        + f'\n[sessions]\ndir = "{(tmp_path / "sessions").as_posix()}"\n',
        encoding="utf-8",
    )
    return path


def test_cli_delegates_a_task_to_a_subagent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _write_config(tmp_path)
    provider = ScriptedProvider(
        [
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=(
                    ToolCall(
                        id="c1", name="delegate", arguments='{"task":"child task"}'
                    ),
                ),
            ),
            Message(role=Role.ASSISTANT, content="child answer"),
            Message(role=Role.ASSISTANT, content="parent final: child answer"),
        ]
    )

    code = main(
        ["run", "-m", "delegate this", "--config", str(config)],
        provider_factory=lambda _settings: provider,
    )

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == "parent final: child answer\n"
    # parent tool call, child turn, then the parent's continuation
    assert len(provider.requests) == 3
    assert [
        (message.role, message.content) for message in provider.requests[1].messages
    ] == [(Role.USER, "child task")]
    results = [
        message for message in provider.requests[2].messages if message.role is Role.TOOL
    ]
    assert [message.content for message in results] == ["child answer"]


class _BackgroundProvider:
    """Answers by request shape, so a concurrent child turn stays deterministic."""

    def stream(self, request: ModelRequest) -> AsyncIterator[StreamEvent]:
        return self._iterate(request)

    async def _iterate(self, request: ModelRequest) -> AsyncIterator[StreamEvent]:
        if [message.content for message in request.messages] == ["child task"]:
            yield TextDelta(text="child answer")
            yield Completed(
                message=Message(role=Role.ASSISTANT, content="child answer")
            )
            return
        if any(message.role is Role.TOOL for message in request.messages):
            yield TextDelta(text="parent done")
            yield Completed(
                message=Message(role=Role.ASSISTANT, content="parent done")
            )
            return
        yield Completed(
            message=Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=(
                    ToolCall(
                        id="c1",
                        name="delegate",
                        arguments='{"action":"start","task":"child task"}',
                    ),
                ),
            )
        )

    async def aclose(self) -> None:
        return None


def test_cli_delivers_a_background_task_result(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _write_config(tmp_path)

    code = main(
        ["run", "-m", "go", "--config", str(config)],
        provider_factory=lambda _settings: _BackgroundProvider(),
    )

    captured = capsys.readouterr()
    assert code == 0
    assert "parent done" in captured.out
    assert "child answer" in captured.out
