"""Shared parsing of MCP JSON-RPC results, validated at the boundary.

Both the stdio and HTTP clients speak the same protocol, so the result shapes
are parsed once here rather than duplicating the models per transport.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from newbot.domain.errors import McpError
from newbot.domain.mcp import McpToolResult, McpToolSpec


class _ToolDefinition(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    name: str = Field(min_length=1)
    description: str = ""
    input_schema: dict[str, object] = Field(default_factory=dict, alias="inputSchema")


class _ListToolsResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tools: list[_ToolDefinition] = Field(default_factory=list)


class _ContentItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str
    text: str | None = None


class _CallToolResult(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    content: list[_ContentItem] = Field(default_factory=list)
    is_error: bool = Field(default=False, alias="isError")


def tool_specs(server: str, result: object) -> tuple[McpToolSpec, ...]:
    """Parse a ``tools/list`` result into normalized specs."""
    try:
        parsed = _ListToolsResult.model_validate(result)
    except ValidationError as exc:
        raise McpError(
            f"mcp server {server!r} returned an invalid tool list: {exc}"
        ) from exc
    return tuple(
        McpToolSpec(
            name=tool.name,
            description=tool.description,
            parameters=tool.input_schema,
        )
        for tool in parsed.tools
    )


def tool_result(server: str, result: object) -> McpToolResult:
    """Parse a ``tools/call`` result into normalized text."""
    try:
        parsed = _CallToolResult.model_validate(result)
    except ValidationError as exc:
        raise McpError(
            f"mcp server {server!r} returned an invalid tool result: {exc}"
        ) from exc
    return McpToolResult(text=_content_text(parsed.content), is_error=parsed.is_error)


def describe_error(error: object) -> str:
    """Render a JSON-RPC error object for a diagnostic message."""
    if isinstance(error, Mapping):
        message = error.get("message")
        code = error.get("code")
        if isinstance(message, str) and message:
            return f"{message} (code {code})" if code is not None else message
    return "unknown error"


def _content_text(items: Sequence[_ContentItem]) -> str:
    parts = [item.text for item in items if item.type == "text" and item.text]
    if not parts:
        return "(no text content)"
    return "\n".join(parts)
