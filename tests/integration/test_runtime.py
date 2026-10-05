"""End-to-end wiring tests for one-shot runs through the composition root."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

from newbot.app.lifecycle import run_once
from newbot.config.schema import Settings
from newbot.domain.message import Message, Role
from newbot.domain.tool import ToolCall
from support import FailingProvider, FakeProvider, ScriptedProvider, reply_events


def _settings(tmp_path: Path) -> Settings:
    return Settings.model_validate(
        {
            "provider": {"base_url": "https://api.example.com/v1", "api_key": "k"},
            "agent": {"model": "gpt-test"},
            "sessions": {"dir": str(tmp_path / "sessions")},
        }
    )


async def test_run_once_streams_reply_and_closes_provider(tmp_path: Path) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    provider = FakeProvider(reply_events("Hello world"))

    code = await run_once(
        _settings(tmp_path),
        "hi",
        provider_factory=lambda _settings: provider,
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert stdout.getvalue() == "Hello world\n"
    assert stderr.getvalue() == ""
    assert provider.closed is True


async def test_run_once_reports_provider_failure(tmp_path: Path) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = await run_once(
        _settings(tmp_path),
        "hi",
        provider_factory=lambda _settings: FailingProvider(),
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 1
    assert "provider down" in stderr.getvalue()


async def test_history_persists_across_runs(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    first = ScriptedProvider([Message(role=Role.ASSISTANT, content="first reply")])
    await run_once(
        settings,
        "first question",
        provider_factory=lambda _settings: first,
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    second = ScriptedProvider([Message(role=Role.ASSISTANT, content="second reply")])
    await run_once(
        settings,
        "second question",
        provider_factory=lambda _settings: second,
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert [message.content for message in second.requests[0].messages] == [
        "first question",
        "first reply",
        "second question",
    ]


async def test_unsupported_sandbox_warns_and_still_runs(tmp_path: Path) -> None:
    name = "bwrap" if sys.platform != "linux" else "seatbelt"
    settings = Settings.model_validate(
        {
            "provider": {"base_url": "https://api.example.com/v1", "api_key": "k"},
            "agent": {"model": "gpt-test"},
            "sessions": {"dir": str(tmp_path / "sessions")},
            "tools": {"sandbox": name},
        }
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = await run_once(
        settings,
        "hi",
        provider_factory=lambda _settings: FakeProvider(reply_events("ok")),
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert stdout.getvalue() == "ok\n"
    assert name in stderr.getvalue()


async def test_extra_read_root_is_wired_through_the_runtime(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    extra = tmp_path / "knowledge"
    extra.mkdir()
    (extra / "doc.md").write_text("reference", encoding="utf-8")
    settings = Settings.model_validate(
        {
            "provider": {"base_url": "https://api.example.com/v1", "api_key": "k"},
            "agent": {"model": "gpt-test", "workspace": str(workspace)},
            "sessions": {"dir": str(tmp_path / "sessions")},
            "tools": {"extraReadDirs": [str(extra)]},
        }
    )
    provider = ScriptedProvider(
        [
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=(
                    ToolCall(
                        id="c1",
                        name="read_file",
                        arguments=json.dumps({"path": str(extra / "doc.md")}),
                    ),
                ),
            ),
            Message(role=Role.ASSISTANT, content="done"),
        ]
    )

    code = await run_once(
        settings,
        "read the knowledge base",
        provider_factory=lambda _settings: provider,
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    tool_messages = [
        message for message in provider.requests[1].messages if message.role is Role.TOOL
    ]
    assert code == 0
    assert tool_messages[0].content == "reference"
