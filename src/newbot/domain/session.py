"""Session identity and persisted-record value types."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TypeAlias

from newbot.domain.message import Message


@dataclass(frozen=True, slots=True)
class SessionKey:
    """Stable identity of one conversation within one transport."""

    transport: str
    conversation: str


@dataclass(frozen=True, slots=True)
class MessageRecord:
    """One persisted conversation message."""

    timestamp: datetime
    message: Message


@dataclass(frozen=True, slots=True)
class CheckpointRecord:
    """A compaction boundary: earlier messages are represented by ``summary``."""

    timestamp: datetime
    summary: str


SessionRecord: TypeAlias = MessageRecord | CheckpointRecord
