"""Session identity and persisted-record value types."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from newbot.domain.message import Message


@dataclass(frozen=True, slots=True)
class SessionKey:
    """Stable identity of one conversation within one transport."""

    transport: str
    conversation: str


@dataclass(frozen=True, slots=True)
class SessionRecord:
    """One persisted conversation entry: a timestamped message."""

    timestamp: datetime
    message: Message
