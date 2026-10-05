"""Deterministic tool registry with allowlist filtering and result normalization."""

from __future__ import annotations

import json
from collections.abc import Collection, Mapping, Sequence

from newbot.domain.errors import NewbotError, ToolError
from newbot.domain.tool import ToolCall, ToolResult, ToolSpec
from newbot.policy.network import NetworkGuard
from newbot.policy.redaction import bound_text
from newbot.policy.sandbox import Sandbox
from newbot.policy.shell import ShellGuard
from newbot.policy.workspace import WorkspaceGuard
from newbot.ports.tools import ToolContext
from newbot.tools.base import Tool
from newbot.tools.filesystem import ListDirTool, ReadFileTool, WriteFileTool
from newbot.tools.shell import DEFAULT_TIMEOUT_SECONDS, ShellTool
from newbot.tools.web import WebFetchTool


class ToolRegistry:
    """Holds enabled tools and normalizes every invocation result."""

    def __init__(
        self, tools: Sequence[Tool], *, allowlist: Collection[str] | None = None
    ) -> None:
        self._tools = _collect(tools, allowlist)

    def specs(self) -> tuple[ToolSpec, ...]:
        """Return enabled specs in a deterministic (name-sorted) order."""
        return tuple(self._tools[name].spec for name in sorted(self._tools))

    async def invoke(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        """Invoke one tool call; failures become bounded error results."""
        tool = self._tools.get(call.name)
        if tool is None:
            return ToolResult(
                call_id=call.id, content=f"unknown tool {call.name!r}", is_error=True
            )
        try:
            arguments = _parse_arguments(call.arguments)
            output = await tool.invoke(arguments, ctx)
        except NewbotError as exc:
            return ToolResult(call_id=call.id, content=bound_text(str(exc)), is_error=True)
        return ToolResult(
            call_id=call.id, content=bound_text(output.text), is_error=output.is_error
        )


def build_default_registry(
    guard: WorkspaceGuard,
    *,
    network_guard: NetworkGuard,
    sandbox: Sandbox | None = None,
    allowlist: Collection[str] | None = None,
    shell_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> ToolRegistry:
    """Construct the built-in tool set, filtered by the agent allowlist."""
    workspace_only = WorkspaceGuard(guard.root)
    tools: list[Tool] = [
        ReadFileTool(guard),
        WriteFileTool(guard),
        ListDirTool(guard),
        ShellTool(
            ShellGuard(workspace_only),
            sandbox=sandbox,
            timeout_seconds=shell_timeout_seconds,
        ),
        WebFetchTool(network_guard),
    ]
    return ToolRegistry(tools, allowlist=allowlist)


def _collect(
    tools: Sequence[Tool], allowlist: Collection[str] | None
) -> dict[str, Tool]:
    selected: dict[str, Tool] = {}
    for tool in tools:
        name = tool.spec.name
        if allowlist is not None and name not in allowlist:
            continue
        if name in selected:
            raise ToolError(f"duplicate tool name {name!r}")
        selected[name] = tool
    return selected


def _parse_arguments(raw: str) -> Mapping[str, object]:
    if not raw.strip():
        return {}
    try:
        parsed: object = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ToolError(f"invalid tool arguments: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ToolError("tool arguments must be a JSON object")
    return parsed
