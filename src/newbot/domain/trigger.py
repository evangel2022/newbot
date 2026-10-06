"""Trigger delivery value types."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TriggerDelivery:
    """One queued message bound to a named local trigger."""

    delivery_id: str
    trigger_id: str
    conversation: str
    text: str
