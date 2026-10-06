"""Integration tests for the stdio MCP client against a real subprocess."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

from newbot.adapters.mcp.stdio import StdioMcpClient
from newbot.app.bootstrap import build_runtime, configured_secrets
from newbot.config.schema import Settings
from newbot.domain.errors import McpError, NetworkAccessDenied
from newbot.domain.mcp import McpStdioServerSpec
from newbot.domain.plugin import Plugin
from support import FakeProvider, reply_events

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "mcp_stub_server.py"


def _spec(*extra: str) -> McpStdioServerSpec:
    return McpStdioServerSpec(
        name="stub", command=sys.executable, args=(str(FIXTURE), *extra)
    )


async def test_a_server_lists_and_answers_its_tools() -> None:
    client = StdioMcpClient(_spec())
    await client.start()
    try:
        tools = await client.list_tools()
        assert [tool.name for tool in tools] == ["echo"]
        assert tools[0].description == "Echo the given text back."
        assert tools[0].parameters["type"] == "object"

        result = await client.call_tool("echo", {"text": "hi"})
        assert result.text == "echo: hi"
        assert result.is_error is False

        failed = await client.call_tool("echo", {"text": "boom"})
        assert failed.text == "echo: boom"
        assert failed.is_error is True
    finally:
        await client.aclose()


async def test_a_closed_client_refuses_further_calls() -> None:
    client = StdioMcpClient(_spec())
    await client.start()
    await client.aclose()

    with pytest.raises(McpError):
        await client.list_tools()


async def test_a_protocol_error_becomes_a_typed_failure() -> None:
    client = StdioMcpClient(_spec("--error"))

    with pytest.raises(McpError) as info:
        await client.start()

    assert "stub refused" in str(info.value)


async def test_a_server_that_exits_is_a_typed_failure() -> None:
    client = StdioMcpClient(
        McpStdioServerSpec(name="stub", command=sys.executable, args=("-c", "pass"))
    )

    with pytest.raises(McpError):
        await client.start()


async def test_a_server_that_cannot_start_is_a_typed_failure() -> None:
    client = StdioMcpClient(
        McpStdioServerSpec(name="stub", command="newbot-missing-command-xyz")
    )

    with pytest.raises(McpError) as info:
        await client.start()

    assert "could not start" in str(info.value)


async def test_a_broken_server_fails_the_whole_startup(tmp_path: Path) -> None:
    settings = Settings.model_validate(
        {
            "provider": {"base_url": "https://api.example.com/v1", "api_key": "k"},
            "agent": {"model": "gpt-test", "workspace": str(tmp_path / "ws")},
            "sessions": {"dir": str(tmp_path / "sessions")},
            "tools": {"mcp": {"servers": {"stub": {"command": "newbot-missing-xyz"}}}},
        }
    )

    with pytest.raises(McpError):
        await build_runtime(
            settings,
            provider_factory=lambda _settings: FakeProvider(reply_events("unused")),
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )


def test_mcp_env_values_are_treated_as_secrets() -> None:
    settings = Settings.model_validate(
        {
            "provider": {
                "base_url": "https://api.example.com/v1",
                "api_key": "provider-key",
            },
            "agent": {"model": "gpt-test"},
            "tools": {
                "mcp": {
                    "servers": {
                        "stub": {"command": "python", "env": {"TOKEN": "mcp-secret"}}
                    }
                }
            },
        }
    )

    secrets = configured_secrets(settings)

    assert "provider-key" in secrets
    assert "mcp-secret" in secrets


def test_plugin_mcp_env_values_are_treated_as_secrets() -> None:
    settings = Settings.model_validate(
        {
            "provider": {
                "base_url": "https://api.example.com/v1",
                "api_key": "provider-key",
            },
            "agent": {"model": "gpt-test"},
        }
    )
    plugin = Plugin(
        name="bundle",
        root=Path("/ws/plugins/bundle"),
        skills=(),
        mcp_servers=(
            McpStdioServerSpec(
                name="stub",
                command="python",
                env={
                    "TOKEN": "plugin-secret",
                    "PLUGIN_ROOT": "/ws/plugins/bundle",
                    "PLUGIN_DATA": "/data/bundle",
                },
            ),
        ),
    )

    secrets = configured_secrets(settings, (plugin,))

    assert "plugin-secret" in secrets
    assert "provider-key" in secrets
    assert "/ws/plugins/bundle" not in secrets
    assert "/data/bundle" not in secrets


async def test_a_private_http_server_fails_the_whole_startup(tmp_path: Path) -> None:
    settings = Settings.model_validate(
        {
            "provider": {"base_url": "https://api.example.com/v1", "api_key": "k"},
            "agent": {"model": "gpt-test", "workspace": str(tmp_path / "ws")},
            "sessions": {"dir": str(tmp_path / "sessions")},
            "tools": {"mcp": {"servers": {"remote": {"url": "http://127.0.0.1/mcp"}}}},
        }
    )

    with pytest.raises(NetworkAccessDenied) as info:
        await build_runtime(
            settings,
            provider_factory=lambda _settings: FakeProvider(reply_events("unused")),
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )

    assert "127.0.0.1" in str(info.value)
