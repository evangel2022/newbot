"""Contract tests for session compaction checkpoints."""

from __future__ import annotations

from newbot.domain.message import Message, Role
from newbot.domain.session import CheckpointRecord, MessageRecord, SessionKey
from newbot.session.manager import SessionManager
from support import FakeSummarizer, MemorySessionStore

KEY = SessionKey(transport="test", conversation="c1")


async def test_compaction_replays_a_summary_plus_recent_messages_verbatim() -> None:
    store = MemorySessionStore()
    manager = SessionManager(store, workspace_id="ws")
    messages = tuple(Message(role=Role.USER, content=f"m{index}") for index in range(6))
    await manager.record(KEY, messages)
    summarizer = FakeSummarizer(summary="earlier turns")

    changed = await manager.compact(KEY, summarizer, keep_recent=2)

    assert changed == "earlier turns"
    assert summarizer.inputs == [messages[:4]]
    records = store.records[("ws", "test", "c1")]
    checkpoints = [record for record in records if isinstance(record, CheckpointRecord)]
    assert [checkpoint.summary for checkpoint in checkpoints] == ["earlier turns"]
    saved = [record.message for record in records if isinstance(record, MessageRecord)]
    assert saved == list(messages)
    assert len(records) == len(messages) + 1
    assert await manager.history(KEY) == (
        Message(role=Role.SYSTEM, content="earlier turns"),
        *messages[4:],
    )


async def test_compaction_folds_the_previous_summary_into_the_next() -> None:
    store = MemorySessionStore()
    manager = SessionManager(store, workspace_id="ws")
    await manager.record(
        KEY, tuple(Message(role=Role.USER, content=f"m{index}") for index in range(6))
    )
    await manager.compact(KEY, FakeSummarizer(summary="first"), keep_recent=2)
    await manager.record(
        KEY,
        (
            Message(role=Role.USER, content="m6"),
            Message(role=Role.USER, content="m7"),
            Message(role=Role.USER, content="m8"),
        ),
    )
    summarizer = FakeSummarizer(summary="second")

    changed = await manager.compact(KEY, summarizer, keep_recent=2)

    assert changed == "second"
    assert summarizer.inputs == [
        (
            Message(role=Role.SYSTEM, content="first"),
            Message(role=Role.USER, content="m4"),
            Message(role=Role.USER, content="m5"),
            Message(role=Role.USER, content="m6"),
        )
    ]
    assert await manager.history(KEY) == (
        Message(role=Role.SYSTEM, content="second"),
        Message(role=Role.USER, content="m7"),
        Message(role=Role.USER, content="m8"),
    )


async def test_compaction_is_a_no_op_when_history_fits() -> None:
    store = MemorySessionStore()
    manager = SessionManager(store, workspace_id="ws")
    await manager.record(KEY, (Message(role=Role.USER, content="hi"),))
    summarizer = FakeSummarizer()

    assert await manager.compact(KEY, summarizer, keep_recent=8) is None
    assert summarizer.inputs == []
    assert len(store.records[("ws", "test", "c1")]) == 1


async def test_auto_compaction_waits_until_the_window_is_exceeded() -> None:
    store = MemorySessionStore()
    manager = SessionManager(store, workspace_id="ws", history_limit=4)
    await manager.record(
        KEY, tuple(Message(role=Role.USER, content=f"m{index}") for index in range(4))
    )
    summarizer = FakeSummarizer()

    assert await manager.compact_when_saturated(KEY, summarizer) is None
    assert summarizer.inputs == []
    assert len(store.records[("ws", "test", "c1")]) == 4


async def test_auto_compaction_folds_the_older_half_of_a_saturated_window() -> None:
    store = MemorySessionStore()
    manager = SessionManager(store, workspace_id="ws", history_limit=4)
    messages = tuple(
        Message(role=Role.USER, content=f"m{index}") for index in range(6)
    )
    await manager.record(KEY, messages)
    summarizer = FakeSummarizer(summary="folded")

    changed = await manager.compact_when_saturated(KEY, summarizer)

    assert changed == "folded"
    assert summarizer.inputs == [messages[:4]]
    assert await manager.history(KEY) == (
        Message(role=Role.SYSTEM, content="folded"),
        messages[4],
        messages[5],
    )
