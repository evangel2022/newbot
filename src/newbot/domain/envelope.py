"""Envelopes exchanged between transports and the core."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class InboundEnvelope:
    """A user message entering the runtime from a transport."""

    transport: str
    conversation_id: str
    text: str


@dataclass(frozen=True, slots=True)
class OutboundEnvelope:
    """A completed reply leaving the runtime for its origin transport."""

    transport: str
    conversation_id: str
    text: str
