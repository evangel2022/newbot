"""The session store interface."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from newbot.domain.message import Message
from newbot.domain.session import SessionKey, SessionRecord


class SessionStorePort(Protocol):
    """Durable storage for one workspace's session records."""

    async def load(
        self, workspace_id: str, key: SessionKey
    ) -> tuple[SessionRecord, ...]:
        """Return every stored record for the session, oldest first."""
        ...

    async def append(
        self, workspace_id: str, key: SessionKey, records: Sequence[SessionRecord]
    ) -> None:
        """Append records durably, never truncating the live file in place."""
        ...


class SessionServicePort(Protocol):
    """The bounded session history and recording the core depends on."""

    async def history(self, key: SessionKey) -> tuple[Message, ...]:
        """Return the replay-safe recent history for a session."""
        ...

    async def record(self, key: SessionKey, messages: Sequence[Message]) -> None:
        """Persist messages as part of a completed turn."""
        ...
