"""Session lifecycle: bounded history reads and turn recording."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from newbot.domain.message import Message, Role
from newbot.domain.session import SessionKey, SessionRecord
from newbot.ports.sessions import SessionStorePort


class SessionManager:
    """Owns session history and recording for one workspace."""

    def __init__(
        self, store: SessionStorePort, *, workspace_id: str, history_limit: int = 40
    ) -> None:
        self._store = store
        self._workspace_id = workspace_id
        self._history_limit = history_limit

    async def history(self, key: SessionKey) -> tuple[Message, ...]:
        """Return the replay-safe recent history for a session."""
        records = await self._store.load(self._workspace_id, key)
        messages = [record.message for record in records]
        return _trim_for_replay(messages, self._history_limit)

    async def record(self, key: SessionKey, messages: Sequence[Message]) -> None:
        """Append messages as timestamped records."""
        if not messages:
            return
        now = datetime.now(UTC)
        records = [
            SessionRecord(timestamp=now, message=message) for message in messages
        ]
        await self._store.append(self._workspace_id, key, records)


def _trim_for_replay(messages: Sequence[Message], limit: int) -> tuple[Message, ...]:
    """Keep the newest messages without orphaning tool results."""
    window = list(messages[-limit:])
    while window and window[0].role is Role.TOOL:
        window.pop(0)
    return tuple(window)
