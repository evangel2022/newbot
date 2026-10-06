"""Contract tests for the session manager against an in-memory store."""

from __future__ import annotations

from newbot.domain.message import Message, Role
from newbot.domain.session import SessionKey
from newbot.domain.tool import ToolCall
from newbot.session.manager import SessionManager
from support import MemorySessionStore

KEY = SessionKey(transport="test", conversation="c1")


async def test_record_appends_timestamped_messages_and_history_returns_them() -> None:
    store = MemorySessionStore()
    manager = SessionManager(store, workspace_id="ws", history_limit=10)
    messages = (
        Message(role=Role.USER, content="hi"),
        Message(role=Role.ASSISTANT, content="hello"),
    )

    await manager.record(KEY, messages)

    records = store.records[("ws", "test", "c1")]
    assert [record.message for record in records] == list(messages)
    assert all(record.timestamp.tzinfo is not None for record in records)
    assert await manager.history(KEY) == messages


async def test_history_keeps_only_the_newest_window() -> None:
    manager = SessionManager(MemorySessionStore(), workspace_id="ws", history_limit=2)
    await manager.record(
        KEY,
        (
            Message(role=Role.USER, content="one"),
            Message(role=Role.ASSISTANT, content="two"),
            Message(role=Role.USER, content="three"),
        ),
    )

    history = await manager.history(KEY)

    assert [message.content for message in history] == ["two", "three"]


async def test_history_never_starts_with_an_orphan_tool_message() -> None:
    manager = SessionManager(MemorySessionStore(), workspace_id="ws", history_limit=2)
    await manager.record(
        KEY,
        (
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=(ToolCall(id="c1", name="read_file", arguments="{}"),),
            ),
            Message(role=Role.TOOL, content="data", tool_call_id="c1"),
            Message(role=Role.ASSISTANT, content="done"),
        ),
    )

    history = await manager.history(KEY)

    assert history == (Message(role=Role.ASSISTANT, content="done"),)


async def test_reset_clears_the_recorded_history() -> None:
    store = MemorySessionStore()
    manager = SessionManager(store, workspace_id="ws", history_limit=10)
    await manager.record(KEY, (Message(role=Role.USER, content="hi"),))

    await manager.reset(KEY)

    assert await manager.history(KEY) == ()
    assert store.records[("ws", "test", "c1")] == []
