"""Subagent delegation: isolated child turns, background control, cancellation."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from pathlib import Path

import pytest

from newbot.core.context import ContextAssembler
from newbot.core.delegation import SubagentManager
from newbot.core.hub import EventHub
from newbot.core.reasoning import ReasoningLoop
from newbot.domain.agent import AgentDefinition
from newbot.domain.errors import ToolError
from newbot.domain.events import ResponseDelta
from newbot.domain.message import Message, Role
from newbot.domain.provider import Completed, ModelRequest, StreamEvent, TextDelta
from newbot.domain.session import SessionKey
from newbot.domain.subagent import SubagentStatus, SubagentTaskRecord
from newbot.domain.tool import ToolCall
from newbot.domain.turn import Budget
from newbot.ports.provider import ProviderPort
from newbot.session.manager import SessionManager
from support import CollectingTransport, MemorySessionStore, ScriptedProvider, StubRegistry

PARENT = SessionKey("cli", "default")


class _BlockingProvider:
    """Blocks each stream until ``release`` is set."""

    def __init__(self, text: str) -> None:
        self._text = text
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    def stream(self, request: ModelRequest) -> AsyncIterator[StreamEvent]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[StreamEvent]:
        self.started.set()
        await self.release.wait()
        yield Completed(message=Message(role=Role.ASSISTANT, content=self._text))

    async def aclose(self) -> None:
        return None


class _PartialProvider:
    """Streams text, then blocks, so a cancellation has a partial to keep."""

    def __init__(self, text: str) -> None:
        self._text = text
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    def stream(self, request: ModelRequest) -> AsyncIterator[StreamEvent]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[StreamEvent]:
        yield TextDelta(text=self._text)
        self.started.set()
        await self.release.wait()
        yield Completed(message=Message(role=Role.ASSISTANT, content=self._text))

    async def aclose(self) -> None:
        return None


class _ConcurrencyProvider:
    """Tracks how many child streams run at once, blocking until released."""

    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self.release = asyncio.Event()

    def stream(self, request: ModelRequest) -> AsyncIterator[StreamEvent]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[StreamEvent]:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await self.release.wait()
            yield Completed(message=Message(role=Role.ASSISTANT, content="ok"))
        finally:
            self.active -= 1

    async def aclose(self) -> None:
        return None


class _MemoryTaskStore:
    def __init__(self, records: tuple[SubagentTaskRecord, ...] = ()) -> None:
        self._records = list(records)

    def load(self) -> tuple[SubagentTaskRecord, ...]:
        return tuple(self._records)

    def save(self, records: Sequence[SubagentTaskRecord]) -> None:
        self._records = list(records)


def _manager(
    provider: ProviderPort,
    *,
    max_iterations: int = 4,
    hub: EventHub | None = None,
    store: _MemoryTaskStore | None = None,
    max_concurrent: int | None = None,
) -> tuple[SubagentManager, SessionManager]:
    session_store = MemorySessionStore()
    sessions = SessionManager(session_store, workspace_id="w", history_limit=10)
    agent = AgentDefinition(
        model="m", system_prompt="sys", budget=Budget(max_iterations=max_iterations)
    )
    registry = StubRegistry()
    manager = SubagentManager(
        sessions=sessions,
        budget=agent.budget,
        hub=hub,
        store=store,
        max_concurrent=max_concurrent,
    )
    manager.bind(
        reasoning=ReasoningLoop(provider, registry),
        assembler=ContextAssembler(agent, registry),
    )
    return manager, sessions


async def test_run_runs_an_isolated_child_turn(tmp_path: Path) -> None:
    provider = ScriptedProvider([Message(role=Role.ASSISTANT, content="child result")])
    manager, sessions = _manager(provider)

    outcome = await manager.run("summarize X", parent=PARENT, workspace_root=tmp_path)

    assert outcome.status is SubagentStatus.COMPLETED
    assert outcome.text == "child result"
    child = SessionKey("cli", "default:sub:1")
    assert [
        (message.role, message.content) for message in await sessions.history(child)
    ] == [(Role.USER, "summarize X"), (Role.ASSISTANT, "child result")]
    assert await sessions.history(PARENT) == ()


async def test_the_child_sees_only_the_task(tmp_path: Path) -> None:
    provider = ScriptedProvider([Message(role=Role.ASSISTANT, content="ok")])
    manager, _ = _manager(provider)

    await manager.run("isolated task", parent=PARENT, workspace_root=tmp_path)

    child_request = provider.requests[0]
    assert [(message.role, message.content) for message in child_request.messages] == [
        (Role.USER, "isolated task")
    ]
    assert child_request.system == "sys"


async def test_a_subagent_cannot_delegate_a_further_task(tmp_path: Path) -> None:
    provider = ScriptedProvider([Message(role=Role.ASSISTANT, content="x")])
    manager, _ = _manager(provider)
    await manager.run("first", parent=PARENT, workspace_root=tmp_path)

    with pytest.raises(ToolError, match="cannot delegate"):
        await manager.start(
            "again",
            parent=SessionKey("cli", "default:sub:1"),
            workspace_root=tmp_path,
        )


async def test_a_child_that_hits_its_budget_is_incomplete(tmp_path: Path) -> None:
    tool_only = Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=(ToolCall(id="c1", name="x", arguments="{}"),),
    )
    manager, _ = _manager(ScriptedProvider([tool_only]), max_iterations=1)

    outcome = await manager.run("loop", parent=PARENT, workspace_root=tmp_path)

    assert outcome.status is SubagentStatus.INCOMPLETE


async def test_start_runs_in_the_background_until_waited_on(tmp_path: Path) -> None:
    provider = _BlockingProvider("bg result")
    manager, _ = _manager(provider)

    started = await manager.start("bg task", parent=PARENT, workspace_root=tmp_path)
    assert started.status is SubagentStatus.RUNNING
    await provider.started.wait()
    assert (await manager.status(started.id, parent=PARENT)).status is (
        SubagentStatus.RUNNING
    )

    provider.release.set()
    done = await manager.wait(started.id, parent=PARENT)

    assert done.status is SubagentStatus.COMPLETED
    assert done.text == "bg result"


async def test_cancelling_one_task_leaves_a_sibling_running(tmp_path: Path) -> None:
    provider = _BlockingProvider("sibling")
    manager, _ = _manager(provider)
    first = await manager.start("a", parent=PARENT, workspace_root=tmp_path)
    second = await manager.start("b", parent=PARENT, workspace_root=tmp_path)
    await provider.started.wait()

    cancelled = await manager.cancel(first.id, parent=PARENT)

    assert cancelled.status is SubagentStatus.CANCELLED
    assert (await manager.status(second.id, parent=PARENT)).status is (
        SubagentStatus.RUNNING
    )
    provider.release.set()
    assert (await manager.wait(second.id, parent=PARENT)).status is (
        SubagentStatus.COMPLETED
    )


async def test_shutdown_cancels_running_tasks(tmp_path: Path) -> None:
    provider = _BlockingProvider("never")
    manager, _ = _manager(provider)
    started = await manager.start("slow", parent=PARENT, workspace_root=tmp_path)
    await provider.started.wait()

    await manager.shutdown()

    assert (await manager.status(started.id, parent=PARENT)).status is (
        SubagentStatus.CANCELLED
    )


async def test_another_conversation_cannot_control_a_task(tmp_path: Path) -> None:
    provider = _BlockingProvider("x")
    manager, _ = _manager(provider)
    started = await manager.start("mine", parent=PARENT, workspace_root=tmp_path)

    with pytest.raises(ToolError, match="another conversation"):
        await manager.status(started.id, parent=SessionKey("cli", "other"))


async def test_an_unknown_task_is_an_error() -> None:
    manager, _ = _manager(ScriptedProvider([]))

    with pytest.raises(ToolError, match="unknown subagent task"):
        await manager.status("task-99", parent=PARENT)


async def test_a_background_task_delivers_its_reply(tmp_path: Path) -> None:
    hub = EventHub()
    transport = CollectingTransport()
    hub.register_transport(transport)
    hub.subscribe(transport)
    provider = ScriptedProvider([Message(role=Role.ASSISTANT, content="reported")])
    manager, _ = _manager(provider, hub=hub)
    parent = SessionKey("test", "ops")

    await manager.start("bg", parent=parent, workspace_root=tmp_path)
    await manager.drain()

    assert [envelope.text for envelope in transport.delivered] == ["reported"]
    assert transport.delivered[0].conversation_id == "ops"
    assert transport.delivered[0].transport == "test"
    deltas = [event for event in transport.events if isinstance(event, ResponseDelta)]
    assert [event.text for event in deltas] == ["reported"]


async def test_a_synchronous_run_does_not_deliver(tmp_path: Path) -> None:
    hub = EventHub()
    transport = CollectingTransport()
    hub.register_transport(transport)
    provider = ScriptedProvider([Message(role=Role.ASSISTANT, content="direct")])
    manager, _ = _manager(provider, hub=hub)

    await manager.run("sync", parent=SessionKey("test", "ops"), workspace_root=tmp_path)

    assert transport.delivered == []


async def test_drain_waits_for_a_running_task(tmp_path: Path) -> None:
    provider = _BlockingProvider("done")
    manager, _ = _manager(provider)
    started = await manager.start("slow", parent=PARENT, workspace_root=tmp_path)
    await provider.started.wait()

    provider.release.set()
    await manager.drain()

    assert (await manager.status(started.id, parent=PARENT)).status is (
        SubagentStatus.COMPLETED
    )


async def test_a_failed_delivery_fails_the_task(tmp_path: Path) -> None:
    hub = EventHub()  # no transport registered for the origin
    provider = ScriptedProvider([Message(role=Role.ASSISTANT, content="lost")])
    manager, _ = _manager(provider, hub=hub)
    started = await manager.start(
        "bg", parent=SessionKey("cli", "default"), workspace_root=tmp_path
    )

    await manager.drain()

    assert (await manager.status(started.id, parent=PARENT)).status is (
        SubagentStatus.FAILED
    )


async def test_a_started_task_is_persisted_as_running(tmp_path: Path) -> None:
    store = _MemoryTaskStore()
    provider = _BlockingProvider("done")
    manager, _ = _manager(provider, store=store)

    started = await manager.start("slow", parent=PARENT, workspace_root=tmp_path)
    assert [(item.id, item.status) for item in store.load()] == [
        (started.id, SubagentStatus.RUNNING)
    ]

    provider.release.set()
    await manager.drain()

    assert [(item.id, item.status) for item in store.load()] == [
        (started.id, SubagentStatus.COMPLETED)
    ]


async def test_a_restart_marks_a_running_task_interrupted(tmp_path: Path) -> None:
    store = _MemoryTaskStore(
        (
            SubagentTaskRecord(
                id="task-1",
                parent=PARENT,
                child=SessionKey("cli", "default:sub:1"),
                status=SubagentStatus.RUNNING,
                text="half",
            ),
        )
    )
    manager, _ = _manager(
        ScriptedProvider([Message(role=Role.ASSISTANT, content="ok")]), store=store
    )

    restored = await manager.status("task-1", parent=PARENT)

    assert restored.status is SubagentStatus.INTERRUPTED
    assert restored.text == "half"
    assert store.load()[0].status is SubagentStatus.INTERRUPTED

    started = await manager.start("next", parent=PARENT, workspace_root=tmp_path)
    assert started.id == "task-2"
    await manager.drain()


async def test_a_cancelled_task_keeps_its_partial_reply(tmp_path: Path) -> None:
    provider = _PartialProvider("partial")
    store = _MemoryTaskStore()
    manager, _ = _manager(provider, store=store)
    started = await manager.start("slow", parent=PARENT, workspace_root=tmp_path)
    await provider.started.wait()

    cancelled = await manager.cancel(started.id, parent=PARENT)

    assert cancelled.status is SubagentStatus.CANCELLED
    assert cancelled.text == "partial"
    assert store.load()[0].status is SubagentStatus.CANCELLED
    assert store.load()[0].text == "partial"


async def test_cancel_session_stops_only_that_session(tmp_path: Path) -> None:
    provider = _BlockingProvider("x")
    manager, _ = _manager(provider)
    first = await manager.start("a", parent=SessionKey("cli", "a"), workspace_root=tmp_path)
    second = await manager.start("b", parent=SessionKey("cli", "b"), workspace_root=tmp_path)
    await provider.started.wait()

    stopped = await manager.cancel_session(SessionKey("cli", "a"))

    assert [task.id for task in stopped] == [first.id]
    assert (await manager.status(first.id, parent=SessionKey("cli", "a"))).status is (
        SubagentStatus.CANCELLED
    )
    assert (await manager.status(second.id, parent=SessionKey("cli", "b"))).status is (
        SubagentStatus.RUNNING
    )
    provider.release.set()
    await manager.drain()


async def test_max_concurrent_bounds_child_turns(tmp_path: Path) -> None:
    provider = _ConcurrencyProvider()
    manager, _ = _manager(provider, max_concurrent=1)
    first = await manager.start("a", parent=PARENT, workspace_root=tmp_path)
    second = await manager.start("b", parent=PARENT, workspace_root=tmp_path)
    for _ in range(5):
        await asyncio.sleep(0)

    assert provider.active == 1

    provider.release.set()
    await manager.drain()

    assert provider.max_active == 1
    assert (await manager.status(first.id, parent=PARENT)).status is (
        SubagentStatus.COMPLETED
    )
    assert (await manager.status(second.id, parent=PARENT)).status is (
        SubagentStatus.COMPLETED
    )
