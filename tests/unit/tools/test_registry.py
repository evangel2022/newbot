"""Contract tests for the tool registry."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from newbot.domain.errors import ToolError
from newbot.domain.session import SessionKey
from newbot.domain.tool import ToolCall, ToolSpec
from newbot.ports.tools import ToolContext
from newbot.tools.base import ToolOutput
from newbot.tools.registry import ToolRegistry

CTX = ToolContext(session=SessionKey("t", "c"), workspace_root=Path("."))


class _EchoTool:
    def __init__(self, name: str = "echo") -> None:
        self.spec = ToolSpec(name=name, description="echo", parameters={"type": "object"})
        self.seen: list[Mapping[str, object]] = []

    async def invoke(
        self, arguments: Mapping[str, object], ctx: ToolContext
    ) -> ToolOutput:
        self.seen.append(arguments)
        return ToolOutput(text=str(arguments.get("text", "")))


class _BoomTool:
    spec = ToolSpec(name="boom", description="", parameters={})

    async def invoke(
        self, arguments: Mapping[str, object], ctx: ToolContext
    ) -> ToolOutput:
        raise ToolError("kaboom")


class _HugeTool:
    spec = ToolSpec(name="huge", description="", parameters={})

    async def invoke(
        self, arguments: Mapping[str, object], ctx: ToolContext
    ) -> ToolOutput:
        return ToolOutput(text="x" * 10_000)


def _call(name: str = "echo", arguments: str = '{"text":"hi"}') -> ToolCall:
    return ToolCall(id="c1", name=name, arguments=arguments)


async def test_invokes_tool_with_parsed_arguments() -> None:
    tool = _EchoTool()
    result = await ToolRegistry([tool]).invoke(_call(), CTX)

    assert result.content == "hi"
    assert result.is_error is False
    assert tool.seen == [{"text": "hi"}]


async def test_unknown_tool_returns_error_result() -> None:
    result = await ToolRegistry([]).invoke(_call(name="nope", arguments="{}"), CTX)

    assert result.is_error is True
    assert "unknown tool" in result.content


async def test_invalid_json_arguments_return_error_result() -> None:
    result = await ToolRegistry([_EchoTool()]).invoke(
        _call(arguments="{not json"), CTX
    )

    assert result.is_error is True


async def test_tool_error_becomes_error_result() -> None:
    result = await ToolRegistry([_BoomTool()]).invoke(
        _call(name="boom", arguments="{}"), CTX
    )

    assert result.is_error is True
    assert "kaboom" in result.content


async def test_large_result_is_bounded() -> None:
    result = await ToolRegistry([_HugeTool()]).invoke(
        _call(name="huge", arguments="{}"), CTX
    )

    assert len(result.content) < 10_000


def test_allowlist_filters_specs() -> None:
    registry = ToolRegistry([_EchoTool("a"), _EchoTool("b")], allowlist={"a"})

    assert [spec.name for spec in registry.specs()] == ["a"]


def test_specs_are_sorted_by_name() -> None:
    registry = ToolRegistry([_EchoTool("b"), _EchoTool("a")])

    assert [spec.name for spec in registry.specs()] == ["a", "b"]


def test_duplicate_tool_names_are_rejected() -> None:
    with pytest.raises(ToolError):
        ToolRegistry([_EchoTool("a"), _EchoTool("a")])
