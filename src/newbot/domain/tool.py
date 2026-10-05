"""Tool value types crossing the model/tool boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """The model-facing description of one tool."""

    name: str
    description: str
    parameters: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ToolCall:
    """One tool invocation requested by the model, with raw JSON arguments."""

    id: str
    name: str
    arguments: str


@dataclass(frozen=True, slots=True)
class ToolResult:
    """A normalized tool outcome ready to feed back to the model."""

    call_id: str
    content: str
    is_error: bool = False
