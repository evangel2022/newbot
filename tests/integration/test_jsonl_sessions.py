"""Integration tests for the JSONL session store boundary."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from newbot.adapters.stores.jsonl_sessions import JsonlSessionStore
from newbot.domain.errors import SessionError
from newbot.domain.message import Message, Role
from newbot.domain.session import CheckpointRecord, MessageRecord, SessionKey
from newbot.domain.tool import ToolCall

KEY = SessionKey(transport="cli", conversation="default")
OTHER_KEY = SessionKey(transport="cli", conversation="other")


async def test_records_survive_a_new_store_instance(tmp_path: Path) -> None:
    records = (
        MessageRecord(
            timestamp=datetime(2026, 10, 5, 1, tzinfo=UTC),
            message=Message(role=Role.USER, content="read it"),
        ),
        MessageRecord(
            timestamp=datetime(2026, 10, 5, 2, tzinfo=UTC),
            message=Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=(
                    ToolCall(id="c1", name="read_file", arguments='{"path":"a"}'),
                ),
            ),
        ),
        MessageRecord(
            timestamp=datetime(2026, 10, 5, 3, tzinfo=UTC),
            message=Message(role=Role.TOOL, content="data", tool_call_id="c1"),
        ),
    )
    await JsonlSessionStore(tmp_path).append("ws-a", KEY, records)

    loaded = await JsonlSessionStore(tmp_path).load("ws-a", KEY)

    assert loaded == records


async def test_append_is_additive_and_scoped_per_workspace_and_session(
    tmp_path: Path,
) -> None:
    store = JsonlSessionStore(tmp_path)
    first = MessageRecord(
        timestamp=datetime(2026, 10, 5, tzinfo=UTC),
        message=Message(role=Role.USER, content="first"),
    )
    second = MessageRecord(
        timestamp=datetime(2026, 10, 5, tzinfo=UTC),
        message=Message(role=Role.USER, content="second"),
    )
    await store.append("ws-a", KEY, (first,))
    await store.append("ws-a", KEY, (second,))
    await store.append("ws-b", KEY, (first,))
    await store.append("ws-a", OTHER_KEY, (first,))

    assert [record.message.content for record in await store.load("ws-a", KEY)] == [
        "first",
        "second",
    ]
    assert len(await store.load("ws-b", KEY)) == 1
    assert len(await store.load("ws-a", OTHER_KEY)) == 1


async def test_malformed_record_raises_session_error(tmp_path: Path) -> None:
    store = JsonlSessionStore(tmp_path)
    await store.append(
        "ws-a",
        KEY,
        (
            MessageRecord(
                timestamp=datetime(2026, 10, 5, tzinfo=UTC),
                message=Message(role=Role.USER, content="hello"),
            ),
        ),
    )
    stored = next(tmp_path.rglob("*.jsonl"))
    stored.write_text(
        stored.read_text(encoding="utf-8") + "{not valid json}\n", encoding="utf-8"
    )

    with pytest.raises(SessionError):
        await store.load("ws-a", KEY)


async def test_checkpoint_records_round_trip(tmp_path: Path) -> None:
    records = (
        MessageRecord(
            timestamp=datetime(2026, 10, 5, 1, tzinfo=UTC),
            message=Message(role=Role.USER, content="hi"),
        ),
        CheckpointRecord(
            timestamp=datetime(2026, 10, 5, 2, tzinfo=UTC),
            summary="earlier turns summarised",
        ),
        MessageRecord(
            timestamp=datetime(2026, 10, 5, 3, tzinfo=UTC),
            message=Message(role=Role.ASSISTANT, content="hello"),
        ),
    )
    await JsonlSessionStore(tmp_path).append("ws-a", KEY, records)

    loaded = await JsonlSessionStore(tmp_path).load("ws-a", KEY)

    assert loaded == records


async def test_rewrite_replaces_every_stored_record(tmp_path: Path) -> None:
    store = JsonlSessionStore(tmp_path)
    await store.append(
        "ws-a",
        KEY,
        (
            MessageRecord(
                timestamp=datetime(2026, 10, 5, tzinfo=UTC),
                message=Message(role=Role.USER, content="old"),
            ),
        ),
    )
    checkpoint = CheckpointRecord(
        timestamp=datetime(2026, 10, 5, tzinfo=UTC), summary="condensed"
    )

    await store.rewrite("ws-a", KEY, (checkpoint,))

    assert await store.load("ws-a", KEY) == (checkpoint,)


async def test_records_without_a_type_load_as_messages(tmp_path: Path) -> None:
    store = JsonlSessionStore(tmp_path)
    record = MessageRecord(
        timestamp=datetime(2026, 10, 5, tzinfo=UTC),
        message=Message(role=Role.USER, content="legacy"),
    )
    await store.append("ws-a", KEY, (record,))
    stored = next(tmp_path.rglob("*.jsonl"))
    stored.write_text(
        stored.read_text(encoding="utf-8").replace('"type": "message", ', ""),
        encoding="utf-8",
    )

    assert await store.load("ws-a", KEY) == (record,)


async def test_unknown_record_type_raises_session_error(tmp_path: Path) -> None:
    store = JsonlSessionStore(tmp_path)
    await store.append(
        "ws-a",
        KEY,
        (
            MessageRecord(
                timestamp=datetime(2026, 10, 5, tzinfo=UTC),
                message=Message(role=Role.USER, content="hi"),
            ),
        ),
    )
    stored = next(tmp_path.rglob("*.jsonl"))
    stored.write_text(
        stored.read_text(encoding="utf-8").replace('"message"', '"bogus"', 1),
        encoding="utf-8",
    )

    with pytest.raises(SessionError):
        await store.load("ws-a", KEY)
