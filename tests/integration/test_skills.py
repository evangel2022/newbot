"""Integration tests for workspace skills wired through the runtime."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from newbot.app.bootstrap import build_runtime
from newbot.config.schema import Settings
from newbot.domain.envelope import InboundEnvelope
from newbot.domain.errors import SkillError
from newbot.domain.message import Message, Role
from newbot.domain.tool import ToolCall
from newbot.domain.turn import TurnStatus
from support import ScriptedProvider


def _settings(
    tmp_path: Path, workspace: Path, *, tools: list[str] | None = None
) -> Settings:
    agent: dict[str, object] = {"model": "gpt-test", "workspace": str(workspace)}
    if tools is not None:
        agent["tools"] = tools
    return Settings.model_validate(
        {
            "provider": {"base_url": "https://api.example.com/v1", "api_key": "k"},
            "agent": agent,
            "sessions": {"dir": str(tmp_path / "sessions")},
        }
    )


def _write_skill(workspace: Path) -> None:
    directory = workspace / "skills" / "greet"
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        "---\ndescription: Say hello nicely\n---\n\nGreet the user warmly.\n",
        encoding="utf-8",
    )


def _runtime(tmp_path: Path, workspace: Path, provider: ScriptedProvider):
    return build_runtime(
        _settings(tmp_path, workspace),
        provider_factory=lambda _settings: provider,
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )


async def test_the_runtime_advertises_and_reads_a_workspace_skill(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "ws"
    _write_skill(workspace)
    provider = ScriptedProvider(
        [
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=(
                    ToolCall(
                        id="c1",
                        name="skill",
                        arguments='{"action": "read", "name": "greet"}',
                    ),
                ),
            ),
            Message(role=Role.ASSISTANT, content="done"),
        ]
    )
    runtime = await _runtime(tmp_path, workspace, provider)
    try:
        status = await runtime.hub.submit(
            InboundEnvelope(transport="cli", conversation_id="default", text="hi")
        )
    finally:
        await runtime.aclose()

    assert status is TurnStatus.COMPLETED
    first = provider.requests[0]
    assert "greet" in first.system
    assert "Say hello nicely" in first.system
    assert "skill" in {spec.name for spec in first.tools}
    second = provider.requests[1]
    outputs = [m.content for m in second.messages if m.role is Role.TOOL]
    assert "Greet the user warmly." in "\n".join(outputs)


async def test_an_allowlist_without_skill_hides_skills(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    _write_skill(workspace)
    provider = ScriptedProvider([Message(role=Role.ASSISTANT, content="ok")])
    runtime = await build_runtime(
        _settings(tmp_path, workspace, tools=["read_file"]),
        provider_factory=lambda _settings: provider,
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    try:
        await runtime.hub.submit(
            InboundEnvelope(transport="cli", conversation_id="default", text="hi")
        )
    finally:
        await runtime.aclose()

    first = provider.requests[0]
    assert "skill" not in {spec.name for spec in first.tools}
    assert "greet" not in first.system


async def test_a_malformed_skill_fails_startup(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    directory = workspace / "skills" / "broken"
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text("no frontmatter here\n", encoding="utf-8")
    provider = ScriptedProvider([Message(role=Role.ASSISTANT, content="ok")])

    with pytest.raises(SkillError):
        await build_runtime(
            _settings(tmp_path, workspace),
            provider_factory=lambda _settings: provider,
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )
