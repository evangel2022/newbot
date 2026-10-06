"""Unit tests for the MCP tool adapter; the server is a local fake."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from newbot.domain.mcp import McpToolResult, McpToolSpec
from newbot.domain.session import SessionKey
from newbot.ports.tools import ToolContext
from newbot.tools.mcp import McpTool


class _FakeClient:
    """A ``McpClientPort`` that records calls and replays one result."""

    def __init__(self, result: McpToolResult) -> None:
        self.server = "echo server"
        self._result = result
        self.calls: list[tuple[str, Mapping[str, object]]] = []

    async def list_tools(self) -> tuple[McpToolSpec, ...]:
        return ()

    async def call_tool(
        self, name: str, arguments: Mapping[str, object]
    ) -> McpToolResult:
        self.calls.append((name, dict(arguments)))
        return self._result

    async def aclose(self) -> None:
        return None


def _context() -> ToolContext:
    return ToolContext(
        session=SessionKey(transport="cli", conversation="default"),
        workspace_root=Path("/tmp"),
    )


async def test_the_model_facing_name_is_namespaced_and_safe() -> None:
    tool = McpTool(
        _FakeClient(McpToolResult(text="ok")),
        McpToolSpec(
            name="echo me",
            description="Echo.",
            parameters={"type": "object"},
        ),
    )

    assert tool.spec.name == "mcp__echo_server__echo_me"
    assert tool.spec.description == "Echo."
    assert tool.spec.parameters == {"type": "object"}


async def test_a_missing_description_names_the_server_and_tool() -> None:
    tool = McpTool(
        _FakeClient(McpToolResult(text="ok")),
        McpToolSpec(name="echo", description="", parameters={}),
    )

    assert "echo" in tool.spec.description
    assert "echo server" in tool.spec.description


async def test_invoking_calls_the_remote_tool_and_normalizes_the_result() -> None:
    client = _FakeClient(McpToolResult(text="echo: hi"))
    tool = McpTool(client, McpToolSpec(name="echo", description="", parameters={}))

    output = await tool.invoke({"text": "hi"}, _context())

    assert output.text == "echo: hi"
    assert output.is_error is False
    assert client.calls == [("echo", {"text": "hi"})]


async def test_a_failed_remote_tool_is_an_error_result() -> None:
    tool = McpTool(
        _FakeClient(McpToolResult(text="bad", is_error=True)),
        McpToolSpec(name="echo", description="", parameters={}),
    )

    output = await tool.invoke({}, _context())

    assert output.is_error is True
