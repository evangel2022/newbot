"""The ``my`` snapshot reports config facts and never carries secrets."""

from __future__ import annotations

import json
from pathlib import Path

from newbot.app.bootstrap import _self_state
from newbot.config.schema import Settings
from newbot.domain.session import SessionKey
from newbot.domain.tool import ToolCall
from newbot.policy.network import NetworkGuard
from newbot.policy.workspace import WorkspaceGuard
from newbot.ports.tools import ToolContext
from newbot.tools.registry import build_default_registry


def _settings() -> Settings:
    return Settings.model_validate(
        {
            "provider": {
                "baseUrl": "https://api.example.com/v1",
                "apiKey": "provider-secret",
            },
            "agent": {"model": "gpt-test", "tools": ["read_file", "my"]},
            "tools": {
                "shellTimeoutSeconds": 12,
                "mcp": {
                    "servers": {
                        "stub": {"command": "python", "env": {"TOKEN": "mcp-secret"}}
                    }
                },
            },
        }
    )


def test_self_state_holds_no_secrets() -> None:
    state = _self_state(_settings())

    assert state["model"] == "gpt-test"
    assert state["provider"] == "openai_compatible"
    assert state["max_iterations"] == 8
    assert state["shell_timeout_seconds"] == 12
    assert state["allowed_tools"] == ["read_file", "my"]
    assert state["mcp_servers"] == ["stub"]
    assert "provider-secret" not in json.dumps(state)
    assert "mcp-secret" not in json.dumps(state)


async def test_the_my_tool_reports_config_without_secrets(tmp_path: Path) -> None:
    registry = build_default_registry(
        WorkspaceGuard(tmp_path),
        network_guard=NetworkGuard(),
        self_state=_self_state(_settings()),
    )
    ctx = ToolContext(session=SessionKey("cli", "default"), workspace_root=tmp_path)

    result = await registry.invoke(
        ToolCall(id="c1", name="my", arguments='{"action":"check"}'), ctx
    )

    assert result.is_error is False
    assert 'model: "gpt-test"' in result.content
    assert "provider-secret" not in result.content
    assert "mcp-secret" not in result.content
