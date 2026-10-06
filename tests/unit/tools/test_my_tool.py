"""Tests for the read-only self-inspection tool."""

from __future__ import annotations

import json
from pathlib import Path

from newbot.domain.session import SessionKey
from newbot.domain.tool import ToolCall
from newbot.policy.network import NetworkGuard
from newbot.policy.workspace import WorkspaceGuard
from newbot.ports.tools import ToolContext
from newbot.tools.registry import ToolRegistry, build_default_registry

_STATE: dict[str, object] = {
    "model": "gpt-test",
    "provider": "openai_compatible",
    "max_iterations": 8,
    "allowed_tools": ["read_file", "my"],
    "mcp_servers": ["stub"],
}


def _ctx(root: Path) -> ToolContext:
    return ToolContext(
        session=SessionKey("cli", "default"), workspace_root=root
    )


def _call(**arguments: object) -> ToolCall:
    return ToolCall(id="c1", name="my", arguments=json.dumps(arguments))


def _registry(root: Path) -> ToolRegistry:
    return build_default_registry(
        WorkspaceGuard(root), network_guard=NetworkGuard(), self_state=_STATE
    )


async def test_check_reports_the_state_and_per_turn_context(tmp_path: Path) -> None:
    result = await _registry(tmp_path).invoke(_call(action="check"), _ctx(tmp_path))

    assert result.is_error is False
    assert 'model: "gpt-test"' in result.content
    assert "max_iterations: 8" in result.content
    assert 'mcp_servers: ["stub"]' in result.content
    assert f"workspace: {json.dumps(str(tmp_path))}" in result.content
    assert 'session: {"conversation": "default", "transport": "cli"}' in result.content


async def test_check_with_a_key_returns_only_that_value(tmp_path: Path) -> None:
    result = await _registry(tmp_path).invoke(
        _call(action="check", key="model"), _ctx(tmp_path)
    )

    assert result.is_error is False
    assert result.content == 'model: "gpt-test"'


async def test_an_unknown_key_is_rejected(tmp_path: Path) -> None:
    result = await _registry(tmp_path).invoke(
        _call(action="check", key="nope"), _ctx(tmp_path)
    )

    assert result.is_error is True
    assert "unknown key" in result.content


async def test_an_unknown_action_is_rejected(tmp_path: Path) -> None:
    result = await _registry(tmp_path).invoke(
        _call(action="set", key="model", value="x"), _ctx(tmp_path)
    )

    assert result.is_error is True
    assert "read-only" in result.content


async def test_a_missing_action_is_rejected(tmp_path: Path) -> None:
    result = await _registry(tmp_path).invoke(_call(), _ctx(tmp_path))

    assert result.is_error is True
