"""Tool contract and argument helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from newbot.domain.errors import ToolError
from newbot.domain.tool import ToolSpec
from newbot.ports.tools import ToolContext


@dataclass(frozen=True, slots=True)
class ToolOutput:
    """A tool's raw output before registry normalization."""

    text: str
    is_error: bool = False


class Tool(Protocol):
    """A model-callable capability with a stable name/schema contract."""

    @property
    def spec(self) -> ToolSpec:
        """The model-facing spec (name, description, JSON schema)."""
        ...

    async def invoke(
        self, arguments: Mapping[str, object], ctx: ToolContext
    ) -> ToolOutput:
        """Run the tool with validated arguments."""
        ...


def require_string(arguments: Mapping[str, object], key: str) -> str:
    """Return a required non-empty string argument or raise ``ToolError``."""
    value = arguments.get(key)
    if not isinstance(value, str) or not value:
        raise ToolError(f"argument {key!r} must be a non-empty string")
    return value
