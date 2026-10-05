"""Contract tests for the reasoning loop against fake ports."""

from __future__ import annotations

from pathlib import Path

import pytest

from newbot.core.reasoning import ReasoningLoop
from newbot.domain.errors import ProviderError
from newbot.domain.events import ResponseDelta
from newbot.domain.message import Message, Role
from newbot.domain.provider import ModelRequest, TextDelta
from newbot.domain.session import SessionKey
from newbot.domain.turn import Budget
from newbot.ports.tools import ToolContext
from support import FakeProvider, RecordingSink, StubRegistry, reply_events

SESSION = SessionKey(transport="cli", conversation="default")
CTX = ToolContext(session=SESSION, workspace_root=Path("."))
REQUEST = ModelRequest(
    model="test-model",
    system="be terse",
    messages=(Message(role=Role.USER, content="hello"),),
)


async def test_streams_deltas_and_returns_final_message() -> None:
    provider = FakeProvider(reply_events("Hello there"))
    sink = RecordingSink()

    result = await ReasoningLoop(provider, StubRegistry()).run(
        REQUEST, session=SESSION, sink=sink, ctx=CTX, budget=Budget(4)
    )

    assert result.message.role is Role.ASSISTANT
    assert result.message.content == "Hello there"
    deltas = [event for event in sink.events if isinstance(event, ResponseDelta)]
    assert "".join(delta.text for delta in deltas) == "Hello there"
    assert all(delta.session == SESSION for delta in deltas)
    assert provider.requests == [REQUEST]


async def test_missing_completion_is_a_provider_error() -> None:
    provider = FakeProvider([TextDelta(text="partial")])

    with pytest.raises(ProviderError):
        await ReasoningLoop(provider, StubRegistry()).run(
            REQUEST, session=SESSION, sink=RecordingSink(), ctx=CTX, budget=Budget(4)
        )
