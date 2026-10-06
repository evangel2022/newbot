"""Session lifecycle: bounded history reads and turn recording."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from newbot.domain.message import Message, Role
from newbot.domain.session import (
    CheckpointRecord,
    MessageRecord,
    SessionKey,
    SessionRecord,
)
from newbot.ports.sessions import SessionStorePort, SummarizerPort


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
        checkpoint, tail = _split_at_last_checkpoint(records)
        return _trim_for_replay(_replayable(checkpoint, tail), self._history_limit)

    async def record(self, key: SessionKey, messages: Sequence[Message]) -> None:
        """Append messages as timestamped records."""
        if not messages:
            return
        now = datetime.now(UTC)
        records = [MessageRecord(timestamp=now, message=message) for message in messages]
        await self._store.append(self._workspace_id, key, records)

    async def reset(self, key: SessionKey) -> None:
        """Discard the session's recorded history, starting it over."""
        await self._store.rewrite(self._workspace_id, key, ())

    async def compact(
        self, key: SessionKey, summarizer: SummarizerPort, *, keep_recent: int
    ) -> str | None:
        """Fold older messages into a checkpoint; return its summary, else None."""
        records = await self._store.load(self._workspace_id, key)
        checkpoint, tail = _split_at_last_checkpoint(records)
        if len(tail) <= keep_recent:
            return None
        return await self._rewrite_with_summary(
            key, records, checkpoint, tail, summarizer, keep_recent=keep_recent
        )

    async def compact_when_saturated(
        self, key: SessionKey, summarizer: SummarizerPort
    ) -> str | None:
        """Fold the older half of an over-full replay window; else None.

        The replay window is ``history_limit`` messages. Once more messages are
        recorded after the last checkpoint than that window can replay, the
        oldest half is folded into a fresh checkpoint so recent turns keep a
        full window without summarizing a single message at a time.
        """
        records = await self._store.load(self._workspace_id, key)
        checkpoint, tail = _split_at_last_checkpoint(records)
        if len(tail) <= self._history_limit:
            return None
        return await self._rewrite_with_summary(
            key,
            records,
            checkpoint,
            tail,
            summarizer,
            keep_recent=max(1, self._history_limit // 2),
        )

    async def _rewrite_with_summary(
        self,
        key: SessionKey,
        records: Sequence[SessionRecord],
        checkpoint: CheckpointRecord | None,
        tail: Sequence[MessageRecord],
        summarizer: SummarizerPort,
        *,
        keep_recent: int,
    ) -> str:
        drop = len(tail) - keep_recent
        summary = await summarizer.summarize(_replayable(checkpoint, tail[:drop]))
        # Keep every saved message; the checkpoint only marks the replay boundary.
        saved = tuple(
            record for record in records if isinstance(record, MessageRecord)
        )
        boundary = len(saved) - keep_recent
        rewritten: tuple[SessionRecord, ...] = (
            *saved[:boundary],
            CheckpointRecord(timestamp=datetime.now(UTC), summary=summary),
            *saved[boundary:],
        )
        await self._store.rewrite(self._workspace_id, key, rewritten)
        return summary


def _split_at_last_checkpoint(
    records: Sequence[SessionRecord],
) -> tuple[CheckpointRecord | None, tuple[MessageRecord, ...]]:
    """Return the newest checkpoint and the message records recorded after it."""
    for index in range(len(records) - 1, -1, -1):
        record = records[index]
        if isinstance(record, CheckpointRecord):
            tail = tuple(
                entry
                for entry in records[index + 1 :]
                if isinstance(entry, MessageRecord)
            )
            return record, tail
    return None, tuple(entry for entry in records if isinstance(entry, MessageRecord))


def _replayable(
    checkpoint: CheckpointRecord | None, tail: Sequence[MessageRecord]
) -> tuple[Message, ...]:
    """Rebuild model-visible messages: the latest summary plus later messages."""
    messages: list[Message] = []
    if checkpoint is not None:
        messages.append(Message(role=Role.SYSTEM, content=checkpoint.summary))
    messages.extend(record.message for record in tail)
    return tuple(messages)


def _trim_for_replay(messages: Sequence[Message], limit: int) -> tuple[Message, ...]:
    """Keep the newest messages without orphaning tool results."""
    window = list(messages[-limit:])
    while window and window[0].role is Role.TOOL:
        window.pop(0)
    return tuple(window)
