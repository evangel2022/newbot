"""The command router intercepts known commands and delegates the rest."""

from __future__ import annotations

from newbot.app.commands import CommandRouter
from newbot.core.hub import EventHub
from newbot.domain.envelope import InboundEnvelope
from newbot.domain.session import SessionKey
from newbot.domain.subagent import SubagentStatus, SubagentTask
from newbot.domain.turn import TurnStatus
from support import CollectingTransport


class _StubEngine:
    def __init__(self) -> None:
        self.envelopes: list[InboundEnvelope] = []

    async def handle(self, envelope: InboundEnvelope) -> TurnStatus:
        self.envelopes.append(envelope)
        return TurnStatus.COMPLETED


class _StubSubagents:
    def __init__(self, cancelled: tuple[SubagentTask, ...] = ()) -> None:
        self._cancelled = cancelled
        self.sessions: list[SessionKey] = []

    async def cancel_session(self, parent: SessionKey) -> tuple[SubagentTask, ...]:
        self.sessions.append(parent)
        return self._cancelled


class _StubSessions:
    def __init__(self) -> None:
        self.reset_keys: list[SessionKey] = []

    async def reset(self, key: SessionKey) -> None:
        self.reset_keys.append(key)


def _router(
    subagents: _StubSubagents | None = None,
    sessions: _StubSessions | None = None,
) -> tuple[
    CommandRouter, _StubEngine, _StubSubagents, _StubSessions, CollectingTransport
]:
    hub = EventHub()
    transport = CollectingTransport()
    hub.register_transport(transport)
    engine = _StubEngine()
    stubs = subagents or _StubSubagents()
    session_stub = sessions or _StubSessions()
    router = CommandRouter(  # type: ignore[arg-type]
        engine=engine, hub=hub, subagents=stubs, sessions=session_stub
    )
    return router, engine, stubs, session_stub, transport


async def test_stop_cancels_the_conversations_tasks() -> None:
    stopped = (SubagentTask("task-1", SubagentStatus.CANCELLED, ""),)
    router, engine, subagents, _, transport = _router(_StubSubagents(stopped))

    status = await router.handle(InboundEnvelope("test", "ops", "/stop"))

    assert status is TurnStatus.COMPLETED
    assert subagents.sessions == [SessionKey("test", "ops")]
    assert [envelope.text for envelope in transport.delivered] == [
        "stopped 1 subagent task(s)"
    ]
    assert engine.envelopes == []


async def test_stop_reports_nothing_running() -> None:
    router, _, _, _, transport = _router()

    await router.handle(InboundEnvelope("test", "ops", "/stop"))

    assert [envelope.text for envelope in transport.delivered] == [
        "no running subagent tasks"
    ]


async def test_help_lists_commands() -> None:
    router, _, _, _, transport = _router()

    await router.handle(InboundEnvelope("test", "ops", "/help"))

    assert "/stop" in transport.delivered[0].text
    assert "/new" in transport.delivered[0].text


async def test_a_plain_message_runs_a_turn() -> None:
    router, engine, _, _, transport = _router()

    await router.handle(InboundEnvelope("test", "ops", "hello"))

    assert [envelope.text for envelope in engine.envelopes] == ["hello"]
    assert transport.delivered == []


async def test_a_command_without_a_reply_is_not_delivered() -> None:
    router, _, _, _, transport = _router()

    status = await router.handle(InboundEnvelope("test", "ops", "/stop", reply=False))

    assert status is TurnStatus.COMPLETED
    assert transport.delivered == []


async def test_new_stops_tasks_and_resets_the_conversation() -> None:
    stopped = (SubagentTask("task-1", SubagentStatus.CANCELLED, ""),)
    router, _, _, sessions, transport = _router(_StubSubagents(stopped))

    await router.handle(InboundEnvelope("test", "ops", "/new"))

    assert sessions.reset_keys == [SessionKey("test", "ops")]
    assert [envelope.text for envelope in transport.delivered] == [
        "stopped 1 subagent task(s); started a new conversation"
    ]
