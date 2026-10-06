"""Envelopes exchanged between transports and the core."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class InboundEnvelope:
    """A message entering the runtime from a transport.

    ``reply`` requests outbound delivery of the turn's reply. Runtime-originated
    work such as a heartbeat records its turn without notifying anyone.
    """

    transport: str
    conversation_id: str
    text: str
    reply: bool = True


@dataclass(frozen=True, slots=True)
class OutboundEnvelope:
    """A completed reply leaving the runtime for its origin transport."""

    transport: str
    conversation_id: str
    text: str
