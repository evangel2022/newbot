"""The terminal transport: streams deltas and delivers turn boundaries."""

from __future__ import annotations

import sys
from typing import TextIO

from newbot.domain.envelope import OutboundEnvelope
from newbot.domain.events import (
    AgentEvent,
    ResponseDelta,
    TurnCompleted,
    TurnFailed,
    TurnStarted,
)
from newbot.domain.turn import TurnStatus


class CliTransport:
    """Renders streamed assistant text and the end of a turn."""

    transport_id = "cli"

    def __init__(
        self, *, stdout: TextIO | None = None, stderr: TextIO | None = None
    ) -> None:
        self._stdout = sys.stdout if stdout is None else stdout
        self._stderr = sys.stderr if stderr is None else stderr
        self._failed = False
        self._status: TurnStatus | None = None

    @property
    def exit_code(self) -> int:
        """Process exit code for the most recent turn."""
        if self._failed or self._status != TurnStatus.COMPLETED:
            return 1
        return 0

    async def publish(self, event: AgentEvent) -> None:
        if event.session.transport != self.transport_id:
            return
        if isinstance(event, TurnStarted):
            self._failed = False
            self._status = None
        elif isinstance(event, ResponseDelta):
            self._stdout.write(event.text)
            self._stdout.flush()
        elif isinstance(event, TurnCompleted):
            self._status = event.status
            if event.status != TurnStatus.COMPLETED:
                self._stderr.write(f"warning: turn incomplete ({event.status.value})\n")
                self._stderr.flush()
        elif isinstance(event, TurnFailed):
            self._failed = True
            self._stderr.write(f"error: {event.message}\n")
            self._stderr.flush()

    async def deliver(self, envelope: OutboundEnvelope) -> None:
        self._stdout.write("\n")
        self._stdout.flush()
