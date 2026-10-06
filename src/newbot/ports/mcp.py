"""The client boundary for connected Model Context Protocol servers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from newbot.domain.mcp import McpToolResult, McpToolSpec


class McpClientPort(Protocol):
    """A connected MCP server owned by the composition root."""

    @property
    def server(self) -> str:
        """The configured server name."""
        ...

    async def list_tools(self) -> tuple[McpToolSpec, ...]:
        """Return the tools the server advertises."""
        ...

    async def call_tool(
        self, name: str, arguments: Mapping[str, object]
    ) -> McpToolResult:
        """Invoke one remote tool by its server-side name."""
        ...

    async def aclose(self) -> None:
        """Stop the server and release its process."""
        ...
