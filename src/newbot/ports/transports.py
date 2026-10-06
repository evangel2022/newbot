"""The transport interface used to deliver outbound replies."""

from __future__ import annotations

from typing import Protocol

from newbot.domain.envelope import InboundEnvelope, OutboundEnvelope
from newbot.domain.turn import TurnStatus


class InboundHandler(Protocol):
    """Receives one inbound envelope; implemented by the turn engine."""

    async def __call__(self, envelope: InboundEnvelope) -> TurnStatus:
        """Handle one inbound envelope and report how its turn ended."""
        ...


class TransportPort(Protocol):
    """A message surface that delivers replies for one transport id."""

    transport_id: str

    async def deliver(self, envelope: OutboundEnvelope) -> None:
        """Deliver one outbound reply."""
        ...
