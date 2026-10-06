"""The tool registry interface and its per-turn context."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from newbot.domain.session import SessionKey
from newbot.domain.tool import ToolCall, ToolResult, ToolSpec


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Per-turn context handed to tools. Tools never read global state."""

    session: SessionKey
    workspace_root: Path


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


class ToolRegistryPort(Protocol):
    """The core's view of the tool registry."""

    def specs(self) -> tuple[ToolSpec, ...]:
        """Return the enabled tool specs, deterministically ordered."""
        ...

    async def invoke(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        """Invoke one tool call, returning a normalized result."""
        ...
