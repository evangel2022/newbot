"""The event-sink interface used for local agent-event fan-out."""

from __future__ import annotations

from typing import Protocol

from newbot.domain.events import AgentEvent


class EventSink(Protocol):
    """Receives typed agent events from the core."""

    async def publish(self, event: AgentEvent) -> None:
        """Handle one agent event."""
        ...
