"""Move envelopes between transports and the turn engine; fan out events."""

from __future__ import annotations

from newbot.domain.envelope import InboundEnvelope, OutboundEnvelope
from newbot.domain.errors import TransportError
from newbot.domain.events import AgentEvent
from newbot.domain.turn import TurnStatus
from newbot.ports.events import EventSink
from newbot.ports.transports import InboundHandler, TransportPort


class EventHub:
    """Routes envelopes and fans typed agent events out to local subscribers."""

    def __init__(self) -> None:
        self._sinks: list[EventSink] = []
        self._transports: dict[str, TransportPort] = {}
        self._inbound: InboundHandler | None = None

    def subscribe(self, sink: EventSink) -> None:
        """Register a local subscriber for typed agent events."""
        self._sinks.append(sink)

    def register_transport(self, transport: TransportPort) -> None:
        """Register a transport for outbound delivery by id."""
        self._transports[transport.transport_id] = transport

    def bind_inbound(self, handler: InboundHandler) -> None:
        """Bind the handler that receives inbound envelopes."""
        self._inbound = handler

    async def publish(self, event: AgentEvent) -> None:
        """Await local subscribers for one typed event."""
        for sink in tuple(self._sinks):
            await sink.publish(event)

    async def submit(self, envelope: InboundEnvelope) -> TurnStatus:
        """Accept inbound work from a transport and report how it ended."""
        handler = self._inbound
        if handler is None:
            raise RuntimeError("no inbound handler bound to the hub")
        return await handler(envelope)

    async def emit(self, envelope: OutboundEnvelope) -> None:
        """Deliver one outbound reply to its origin transport.

        An origin transport that is not registered is a deliberate transport
        failure, so the turn that produced the reply fails rather than raising
        an unhandled error through the caller.
        """
        transport = self._transports.get(envelope.transport)
        if transport is None:
            raise TransportError(
                f"no transport registered for {envelope.transport!r}"
            )
        await transport.deliver(envelope)
