"""Contract tests for the turn engine against fake ports."""

from __future__ import annotations

import asyncio
from pathlib import Path

from newbot.core.context import ContextAssembler
from newbot.core.hub import EventHub
from newbot.core.reasoning import ReasoningLoop
from newbot.core.turn import TurnEngine
from newbot.domain.agent import AgentDefinition
from newbot.domain.envelope import InboundEnvelope
from newbot.domain.events import TurnCompleted, TurnFailed, TurnStarted
from newbot.domain.message import Message, Role
from newbot.domain.turn import Budget, TurnStatus
from newbot.ports.provider import ProviderPort
from newbot.session.manager import SessionManager
from support import (
    CollectingTransport,
    ConcurrencyTrackingProvider,
    FailingProvider,
    FakeProvider,
    MemorySessionStore,
    RecordingSink,
    ScriptedProvider,
    StubRegistry,
    reply_events,
)

AGENT = AgentDefinition(model="test-model", system_prompt="be terse", budget=Budget(4))


def _wire(provider: ProviderPort) -> tuple[EventHub, RecordingSink, CollectingTransport]:
    hub = EventHub()
    sink = RecordingSink()
    transport = CollectingTransport()
    registry = StubRegistry()
    engine = TurnEngine(
        hub=hub,
        reasoning=ReasoningLoop(provider, registry),
        assembler=ContextAssembler(AGENT, registry),
        agent=AGENT,
        workspace_root=Path.cwd(),
        sessions=SessionManager(
            MemorySessionStore(), workspace_id="test", history_limit=40
        ),
    )
    hub.bind_inbound(engine.handle)
    hub.register_transport(transport)
    hub.subscribe(sink)
    return hub, sink, transport


async def test_turn_streams_delivers_and_completes() -> None:
    provider = FakeProvider(reply_events("Hi there"))
    hub, sink, transport = _wire(provider)

    await hub.submit(
        InboundEnvelope(transport="test", conversation_id="c1", text="hello")
    )

    assert isinstance(sink.events[0], TurnStarted)
    completed = sink.events[-1]
    assert isinstance(completed, TurnCompleted)
    assert completed.status is TurnStatus.COMPLETED
    assert transport.delivered[0].text == "Hi there"
    assert transport.delivered[0].conversation_id == "c1"
    assert provider.requests[0].model == "test-model"
    assert provider.requests[0].system == "be terse"
    assert provider.requests[0].messages[0].content == "hello"


async def test_provider_failure_fails_the_turn_without_delivery() -> None:
    hub, sink, transport = _wire(FailingProvider())

    await hub.submit(
        InboundEnvelope(transport="test", conversation_id="c1", text="hello")
    )

    failed = sink.events[-1]
    assert isinstance(failed, TurnFailed)
    assert "provider down" in failed.message
    assert transport.delivered == []


async def test_turns_for_one_session_are_serialized() -> None:
    provider = ConcurrencyTrackingProvider()
    hub, _sink, _transport = _wire(provider)

    await asyncio.gather(
        hub.submit(InboundEnvelope(transport="test", conversation_id="c1", text="one")),
        hub.submit(InboundEnvelope(transport="test", conversation_id="c1", text="two")),
    )

    assert provider.max_concurrent == 1


async def test_turn_history_is_replayed_into_the_next_turn() -> None:
    provider = ScriptedProvider(
        [
            Message(role=Role.ASSISTANT, content="first reply"),
            Message(role=Role.ASSISTANT, content="second reply"),
        ]
    )
    hub, _sink, _transport = _wire(provider)

    await hub.submit(InboundEnvelope(transport="test", conversation_id="c1", text="q1"))
    await hub.submit(InboundEnvelope(transport="test", conversation_id="c1", text="q2"))

    assert [message.content for message in provider.requests[1].messages] == [
        "q1",
        "first reply",
        "q2",
    ]
