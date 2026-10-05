"""Behavior validation at the public boundary; see docs/behavior-matrix.md.

Existing suites already protect several contracts (the matrix cites them by name).
This module adds only the contracts that were not covered at a public boundary,
plus ``xfail`` tests for the two known defects (A1, A2) so the divergence stays
visible and is removed when fixed.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from newbot.adapters.providers.registry import build_provider
from newbot.app.bootstrap import Runtime, build_runtime, build_sessions
from newbot.cli.entry import main
from newbot.config.loader import load_settings
from newbot.config.schema import Settings
from newbot.domain.envelope import InboundEnvelope
from newbot.domain.errors import ConfigLoadError
from newbot.domain.message import Message, Role
from newbot.domain.session import SessionKey
from newbot.domain.tool import ToolCall
from newbot.memory.layout import MemoryLayout
from newbot.ports.provider import ProviderPort
from support import (
    FailingProvider,
    FakeProvider,
    FakeSummarizer,
    ScriptedProvider,
    reply_events,
)


def _settings(
    tmp_path: Path, *, provider_name: str = "openai_compatible", sessions: bool = True
) -> Settings:
    workspace = tmp_path / "ws"
    workspace.mkdir(exist_ok=True)
    payload: dict[str, object] = {
        "provider": {
            "name": provider_name,
            "base_url": "https://api.example.com/v1",
            "api_key": "k",
        },
        "agent": {"model": "gpt-test", "workspace": str(workspace)},
    }
    if sessions:
        payload["sessions"] = {"dir": str(tmp_path / "sessions")}
    return Settings.model_validate(payload)


def _runtime(settings: Settings, provider: ProviderPort) -> Runtime:
    return build_runtime(
        settings,
        provider_factory=lambda _settings: provider,
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )


# --- CLI -------------------------------------------------------------------


def test_cli_reports_a_version_and_rejects_unknown_commands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CLI: the version flag succeeds and a usage error exits 2 without a traceback."""
    with pytest.raises(SystemExit) as version:
        main(["--version"])
    assert version.value.code == 0
    assert capsys.readouterr().out.startswith("newbot ")

    with pytest.raises(SystemExit) as unknown:
        main(["not-a-command"])
    assert unknown.value.code == 2


def test_cli_init_creates_defaults_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """CLI: init creates config + workspace with secret references, never overwriting."""
    config = tmp_path / "instance" / "config.toml"
    workspace = tmp_path / "instance" / "workspace"

    assert main(["init", "--config", str(config), "--workspace", str(workspace)]) == 0
    text = config.read_text(encoding="utf-8")
    assert "${NEWBOT_API_KEY}" in text
    assert workspace.is_dir()

    assert main(["init", "--config", str(config), "--workspace", str(workspace)]) == 0
    assert config.read_text(encoding="utf-8") == text
    assert "already exists" in capsys.readouterr().out


# --- Agent loop / error handling -------------------------------------------


async def test_a_failed_turn_is_reported_as_a_result_not_an_exception(
    tmp_path: Path,
) -> None:
    """Agent loop: a deliberate failure becomes TurnFailed and a non-zero exit."""
    stderr = io.StringIO()
    runtime = build_runtime(
        _settings(tmp_path),
        provider_factory=lambda _settings: FailingProvider(),
        stdout=io.StringIO(),
        stderr=stderr,
    )

    await runtime.hub.submit(
        InboundEnvelope(transport="cli", conversation_id="default", text="hi")
    )

    assert runtime.transport.exit_code == 1
    assert "provider down" in stderr.getvalue()


# --- LLM -------------------------------------------------------------------


def test_unknown_provider_name_fails_fast(tmp_path: Path) -> None:
    """LLM: provider selection is explicit and traceable (ADR-006/A3)."""
    settings = _settings(tmp_path, provider_name="not-a-provider")

    with pytest.raises(ConfigLoadError) as info:
        build_provider(settings.provider)

    assert "unknown provider" in str(info.value)


# --- Tool calling / security ----------------------------------------------


async def test_path_escape_denial_is_a_bounded_tool_result(tmp_path: Path) -> None:
    """Tools/Security: a traversal reads nothing and returns an error result."""
    (tmp_path / "secret.txt").write_text("classified", encoding="utf-8")
    provider = ScriptedProvider(
        [
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=(
                    ToolCall(
                        id="c1", name="read_file", arguments='{"path":"../secret.txt"}'
                    ),
                ),
            ),
            Message(role=Role.ASSISTANT, content="I could not read it"),
        ]
    )
    runtime = build_runtime(
        _settings(tmp_path),
        provider_factory=lambda _settings: provider,
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    await runtime.hub.submit(
        InboundEnvelope(transport="cli", conversation_id="default", text="read it")
    )

    tool_message = [
        message for message in provider.requests[1].messages if message.role is Role.TOOL
    ][-1]
    assert "classified" not in tool_message.content
    assert "denied" in tool_message.content


# --- Session ---------------------------------------------------------------


async def test_sessions_are_isolated_per_transport(tmp_path: Path) -> None:
    """Session: the key is transport + conversation; no unified session by default."""
    runtime = _runtime(_settings(tmp_path), FakeProvider(reply_events("pong")))

    await runtime.hub.submit(
        InboundEnvelope(transport="cli", conversation_id="c", text="cli-only")
    )

    other = await runtime.sessions.history(SessionKey(transport="webui", conversation="c"))
    mine = await runtime.sessions.history(SessionKey(transport="cli", conversation="c"))
    assert other == ()
    assert [message.content for message in mine] == ["cli-only", "pong"]


async def test_session_files_live_outside_the_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Session/Security: history is stored outside the agent-accessible workspace."""
    monkeypatch.setenv("NEWBOT_CONFIG_DIR", str(tmp_path / "cfg"))
    runtime = _runtime(_settings(tmp_path, sessions=False), FakeProvider(reply_events("pong")))

    await runtime.hub.submit(
        InboundEnvelope(transport="cli", conversation_id="c", text="hi")
    )

    assert list((tmp_path / "cfg" / "sessions").rglob("*.jsonl"))
    assert not list((tmp_path / "ws").rglob("*.jsonl"))


# --- Memory ----------------------------------------------------------------


def test_memory_layout_is_confined_to_the_workspace(tmp_path: Path) -> None:
    """Memory: durable files and history all live under the agent workspace."""
    layout = MemoryLayout(tmp_path / "ws")

    paths = (*layout.durable_files, layout.journal, layout.cursors)
    assert all(path.is_relative_to(tmp_path / "ws") for path in paths)
    assert len(set(paths)) == len(paths)


# --- Configuration ---------------------------------------------------------


@pytest.mark.xfail(reason="A2: only whole-value ${VAR} references expand", strict=False)
def test_env_reference_inside_a_larger_string_is_expanded(tmp_path: Path) -> None:
    """Configuration: any string value may embed ${VAR} (nanobot configuration.md)."""
    path = tmp_path / "config.toml"
    path.write_text(
        "[provider]\n"
        'baseUrl = "https://api.example.com/v1"\n'
        'apiKey = "Bearer ${SMOKE_TOKEN}"\n\n'
        "[agent]\n"
        'model = "m"\n',
        encoding="utf-8",
    )

    settings = load_settings(path, environ={"SMOKE_TOKEN": "s3cret"})

    assert settings.provider.api_key == "Bearer s3cret"


# --- Session (known defect) ------------------------------------------------


@pytest.mark.xfail(reason="A1: compaction rewrites the session and drops history", strict=False)
async def test_compaction_keeps_saved_history_on_disk(tmp_path: Path) -> None:
    """Session: /compact bounds context without destroying saved history (ADR-005)."""
    manager = build_sessions(_settings(tmp_path))
    key = SessionKey(transport="cli", conversation="default")
    for index in range(6):
        await manager.record(key, (Message(role=Role.USER, content=f"msg-{index}"),))

    await manager.compact(key, FakeSummarizer("summary"), keep_recent=2)

    stored = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / "sessions").rglob("*.jsonl")
    )
    assert "msg-0" in stored
