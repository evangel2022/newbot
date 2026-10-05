"""The tool registry interface and its per-turn context."""

from __future__ import annotations

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


class ToolRegistryPort(Protocol):
    """The core's view of the tool registry."""

    def specs(self) -> tuple[ToolSpec, ...]:
        """Return the enabled tool specs, deterministically ordered."""
        ...

    async def invoke(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        """Invoke one tool call, returning a normalized result."""
        ...
