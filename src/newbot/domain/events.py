"""Typed agent events published to local subscribers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from newbot.domain.session import SessionKey
from newbot.domain.turn import TurnStatus


@dataclass(frozen=True, slots=True)
class TurnStarted:
    """A turn has been accepted and started for a session."""

    session: SessionKey


@dataclass(frozen=True, slots=True)
class ResponseDelta:
    """Assistant text streamed to the origin transport."""

    session: SessionKey
    text: str


@dataclass(frozen=True, slots=True)
class TurnCompleted:
    """A turn finished successfully."""

    session: SessionKey
    status: TurnStatus


@dataclass(frozen=True, slots=True)
class TurnFailed:
    """A turn failed with a deliberate, reportable error."""

    session: SessionKey
    message: str


AgentEvent: TypeAlias = TurnStarted | ResponseDelta | TurnCompleted | TurnFailed
