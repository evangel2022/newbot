"""Value types for Model Context Protocol servers and their tools."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

MCP_PROTOCOL_VERSION = "2024-11-05"


@dataclass(frozen=True, slots=True)
class McpStdioServerSpec:
    """A configured stdio MCP server the composition root can launch."""

    name: str
    command: str
    args: tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class McpHttpServerSpec:
    """A configured HTTP MCP server the composition root can reach."""

    name: str
    url: str


@dataclass(frozen=True, slots=True)
class McpToolSpec:
    """One tool a connected server advertises, as parsed from ``tools/list``."""

    name: str
    description: str
    parameters: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class McpToolResult:
    """A normalized ``tools/call`` outcome ready to feed back to the model."""

    text: str
    is_error: bool = False
