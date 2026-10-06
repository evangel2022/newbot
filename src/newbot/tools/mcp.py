"""Adapters that expose remote MCP tools through the local tool contract."""

from __future__ import annotations

import re
from collections.abc import Mapping

from newbot.domain.mcp import McpToolSpec
from newbot.domain.tool import ToolSpec
from newbot.ports.mcp import McpClientPort
from newbot.ports.tools import ToolContext
from newbot.tools.base import ToolOutput

_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")
_NAME_PREFIX = "mcp"


class McpTool:
    """One tool advertised by a connected MCP server.

    The model-facing name is namespaced as ``mcp__<server>__<tool>`` so it
    cannot collide with a built-in, and the server-side name is kept verbatim
    for the actual ``tools/call``. The remote schema is passed through
    unchanged: the server owns its tool's arguments.
    """

    def __init__(self, client: McpClientPort, spec: McpToolSpec) -> None:
        self._client = client
        self._remote_name = spec.name
        self.spec = ToolSpec(
            name=f"{_NAME_PREFIX}__{_safe(client.server)}__{_safe(spec.name)}",
            description=spec.description
            or f"MCP tool {spec.name!r} from server {client.server!r}",
            parameters=spec.parameters,
        )

    async def invoke(
        self, arguments: Mapping[str, object], ctx: ToolContext
    ) -> ToolOutput:
        result = await self._client.call_tool(self._remote_name, arguments)
        return ToolOutput(text=result.text, is_error=result.is_error)


def _safe(value: str) -> str:
    return _UNSAFE.sub("_", value)
