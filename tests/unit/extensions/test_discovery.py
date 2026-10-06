"""Entry-point tool discovery validates, sorts, and traces its results."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from newbot.domain.errors import ExtensionError
from newbot.domain.tool import ToolSpec
from newbot.extensions import discovery
from newbot.extensions.discovery import DISCOVERY_GROUP, discover_tools
from newbot.policy.network import NetworkGuard
from newbot.policy.workspace import WorkspaceGuard
from newbot.ports.tools import ToolContext, ToolOutput
from newbot.tools.registry import ToolRegistry, build_default_registry


class _StubTool:
    def __init__(self, name: str) -> None:
        self.spec = ToolSpec(
            name=name, description="stub tool", parameters={"type": "object"}
        )

    async def invoke(
        self, arguments: Mapping[str, object], ctx: ToolContext
    ) -> ToolOutput:
        return ToolOutput(text="ok")


class _EntryPoint:
    def __init__(self, name: str, loaded: object) -> None:
        self.name = name
        self._loaded = loaded

    def load(self) -> object:
        return self._loaded


class _BrokenEntryPoint(_EntryPoint):
    def __init__(self) -> None:
        super().__init__("broken", None)

    def load(self) -> object:
        raise ImportError("no such module")


def _registered_names(registry: ToolRegistry) -> set[str]:
    return {spec.name for spec in registry.specs()}


def test_discovery_returns_tools_sorted_by_entry_point_name() -> None:
    points = [
        _EntryPoint("zeta", lambda: _StubTool("z_tool")),
        _EntryPoint("alpha", lambda: _StubTool("a_tool")),
    ]

    found = discover_tools(entry_points=points)

    assert [item.origin for item in found] == ["alpha", "zeta"]
    assert [item.tool.spec.name for item in found] == ["a_tool", "z_tool"]


def test_discovery_queries_the_public_group(monkeypatch: pytest.MonkeyPatch) -> None:
    groups: list[str] = []

    def _entry_points(*, group: str) -> list[object]:
        groups.append(group)
        return []

    monkeypatch.setattr(discovery.metadata, "entry_points", _entry_points)

    assert discover_tools() == ()
    assert groups == [DISCOVERY_GROUP]


def test_discovery_rejects_an_entry_point_that_fails_to_import() -> None:
    with pytest.raises(ExtensionError, match="could not be imported"):
        discover_tools(entry_points=[_BrokenEntryPoint()])


def test_discovery_rejects_a_non_callable_entry_point() -> None:
    with pytest.raises(ExtensionError, match="must resolve to a factory"):
        discover_tools(entry_points=[_EntryPoint("bad", 42)])


def test_discovery_rejects_a_factory_that_raises() -> None:
    def _explode() -> object:
        raise RuntimeError("boom")

    with pytest.raises(ExtensionError, match="failed to build a tool"):
        discover_tools(entry_points=[_EntryPoint("bad", _explode)])


def test_discovery_rejects_a_value_without_a_spec() -> None:
    with pytest.raises(ExtensionError, match="with a ToolSpec"):
        discover_tools(entry_points=[_EntryPoint("bad", lambda: object())])


def test_discovery_rejects_an_empty_tool_name() -> None:
    with pytest.raises(ExtensionError, match="empty name"):
        discover_tools(entry_points=[_EntryPoint("bad", lambda: _StubTool(""))])


def test_discovery_rejects_a_tool_without_invoke() -> None:
    class _NoInvoke:
        def __init__(self) -> None:
            self.spec = ToolSpec(name="no_invoke", description="x", parameters={})

    with pytest.raises(ExtensionError, match="without invoke"):
        discover_tools(entry_points=[_EntryPoint("bad", _NoInvoke)])


def test_discovery_rejects_two_entry_points_with_the_same_tool_name() -> None:
    points = [
        _EntryPoint("one", lambda: _StubTool("dup")),
        _EntryPoint("two", lambda: _StubTool("dup")),
    ]

    with pytest.raises(ExtensionError, match="provided by both"):
        discover_tools(entry_points=points)


def _extra_registry(
    tmp_path: Path, *, allowlist: list[str] | None = None
) -> ToolRegistry:
    found = discover_tools(
        entry_points=[_EntryPoint("extra", lambda: _StubTool("extra_tool"))]
    )
    return build_default_registry(
        WorkspaceGuard(tmp_path),
        network_guard=NetworkGuard(),
        allowlist=allowlist,
        discovered_tools=tuple(item.tool for item in found),
    )


def test_registry_includes_a_discovered_tool(tmp_path: Path) -> None:
    registry = _extra_registry(tmp_path)

    assert "extra_tool" in _registered_names(registry)


def test_registry_allowlist_filters_a_discovered_tool(tmp_path: Path) -> None:
    registry = _extra_registry(tmp_path, allowlist=["read_file"])

    names = _registered_names(registry)
    assert "read_file" in names
    assert "extra_tool" not in names
