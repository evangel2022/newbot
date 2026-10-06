"""Deterministic entry-point tool discovery (ADR-026).

Entry points are the only way a third-party distribution can add a tool. The
composition root owns the call: discovery never mutates the registry itself,
and every discovered tool keeps its provenance so an operator can trace an
enabled capability to the distribution that provided it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from importlib import metadata
from typing import Protocol, cast

from newbot.domain.errors import ExtensionError
from newbot.domain.tool import ToolSpec
from newbot.ports.tools import Tool

DISCOVERY_GROUP = "newbot.tools"


class ToolEntryPoint(Protocol):
    """The minimal entry-point shape discovery needs from ``importlib``."""

    @property
    def name(self) -> str:
        """The distribution-chosen entry-point name."""
        ...

    def load(self) -> object:
        """Import and return the object the entry point points at."""
        ...


@dataclass(frozen=True, slots=True)
class DiscoveredTool:
    """One validated tool plus the entry point that supplied it."""

    origin: str
    tool: Tool


def discover_tools(
    group: str = DISCOVERY_GROUP,
    *,
    entry_points: Sequence[ToolEntryPoint] | None = None,
) -> tuple[DiscoveredTool, ...]:
    """Load every entry point in ``group`` as a zero-argument tool factory.

    Discovery is deterministic (name-sorted) and fails fast: an entry point
    that cannot import, that does not resolve to a callable, or whose callable
    does not return a valid tool aborts startup with a located error rather
    than silently dropping the capability.
    """
    points = (
        tuple(entry_points)
        if entry_points is not None
        else tuple(metadata.entry_points(group=group))
    )
    discovered: list[DiscoveredTool] = []
    origins: dict[str, str] = {}
    for point in sorted(points, key=lambda item: item.name):
        tool = _validate(point, _build(point))
        name = tool.spec.name
        if name in origins:
            raise ExtensionError(
                f"tool {name!r} is provided by both {origins[name]!r} and "
                f"{point.name!r}"
            )
        origins[name] = point.name
        discovered.append(DiscoveredTool(origin=point.name, tool=tool))
    return tuple(discovered)


def _build(point: ToolEntryPoint) -> object:
    try:
        loaded = point.load()
    except Exception as exc:
        raise ExtensionError(
            f"tool entry point {point.name!r} could not be imported: {exc}"
        ) from exc
    if not callable(loaded):
        raise ExtensionError(
            f"tool entry point {point.name!r} must resolve to a factory"
        )
    factory = cast("Callable[[], object]", loaded)
    try:
        return factory()
    except Exception as exc:
        raise ExtensionError(
            f"tool entry point {point.name!r} failed to build a tool: {exc}"
        ) from exc


def _validate(point: ToolEntryPoint, built: object) -> Tool:
    spec = getattr(built, "spec", None)
    if not isinstance(spec, ToolSpec):
        raise ExtensionError(
            f"tool entry point {point.name!r} did not return a tool with a ToolSpec"
        )
    if not spec.name:
        raise ExtensionError(
            f"tool entry point {point.name!r} returned a tool with an empty name"
        )
    if not callable(getattr(built, "invoke", None)):
        raise ExtensionError(
            f"tool entry point {point.name!r} returned a tool without invoke()"
        )
    return cast(Tool, built)
