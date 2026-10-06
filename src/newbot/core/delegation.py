"""In-process subagent delegation (ADR-029, ADR-031, ADR-032, ADR-033).

A delegated task runs as a child turn on a child session with its own
context. Tasks can run synchronously or in the background, be waited on or
cancelled, and their registry is persisted so an unfinished task is marked
interrupted when the process restarts.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from newbot.core.context import ContextAssembler
from newbot.core.hub import EventHub
from newbot.core.reasoning import ReasoningLoop, ReasoningResult
from newbot.domain.envelope import OutboundEnvelope
from newbot.domain.errors import NewbotError, ToolError
from newbot.domain.events import AgentEvent, ResponseDelta
from newbot.domain.message import Message, Role
from newbot.domain.session import SessionKey
from newbot.domain.subagent import SubagentStatus, SubagentTask, SubagentTaskRecord
from newbot.domain.turn import Budget, TurnStatus
from newbot.ports.sessions import SessionServicePort
from newbot.ports.subagents import SubagentTaskStorePort
from newbot.ports.tools import ToolContext

_CHILD_MARKER = "sub"
_TASK_PREFIX = "task-"


class _RecordingSink:
    """Records a child's streamed text so an interrupted task keeps a partial."""

    def __init__(self) -> None:
        self._parts: list[str] = []

    @property
    def text(self) -> str:
        return "".join(self._parts)

    async def publish(self, event: AgentEvent) -> None:
        if isinstance(event, ResponseDelta):
            self._parts.append(event.text)


@dataclass(slots=True)
class _Running:
    """The manager's mutable record for one delegated task."""

    id: str
    parent: SessionKey
    child: SessionKey
    status: SubagentStatus = SubagentStatus.RUNNING
    text: str = ""
    deliver: bool = False
    handle: asyncio.Task[None] | None = None
    sink: _RecordingSink | None = None

    def view(self) -> SubagentTask:
        return SubagentTask(id=self.id, status=self.status, text=self.text)

    def record(self) -> SubagentTaskRecord:
        return SubagentTaskRecord(
            id=self.id,
            parent=self.parent,
            child=self.child,
            status=self.status,
            text=self.text,
        )


class SubagentManager:
    """Runs delegated tasks as child turns on isolated child sessions.

    The composition root builds the manager before the registry (the
    ``delegate`` tool holds it) and calls :meth:`bind` once the shared
    reasoning loop and assembler exist, which keeps the object graph acyclic.
    """

    def __init__(
        self,
        *,
        sessions: SessionServicePort,
        budget: Budget,
        hub: EventHub | None = None,
        store: SubagentTaskStorePort | None = None,
        max_concurrent: int | None = None,
    ) -> None:
        self._sessions = sessions
        self._budget = budget
        self._hub = hub
        self._store = store
        self._turns = (
            None if max_concurrent is None else asyncio.Semaphore(max_concurrent)
        )
        self._reasoning: ReasoningLoop | None = None
        self._assembler: ContextAssembler | None = None
        self._tasks: dict[str, _Running] = {}
        self._children: set[SessionKey] = set()
        self._counter = 0
        if store is not None:
            self._restore(store.load())

    def _restore(self, records: tuple[SubagentTaskRecord, ...]) -> None:
        interrupted = False
        for record in records:
            status = record.status
            if status is SubagentStatus.RUNNING:
                status = SubagentStatus.INTERRUPTED
                interrupted = True
            self._tasks[record.id] = _Running(
                id=record.id,
                parent=record.parent,
                child=record.child,
                status=status,
                text=record.text,
            )
            self._children.add(record.child)
            self._counter = max(self._counter, _ordinal(record.id))
        if interrupted:
            self._persist()

    def bind(
        self, *, reasoning: ReasoningLoop, assembler: ContextAssembler
    ) -> None:
        """Attach the shared reasoning loop and assembler (composition root)."""
        self._reasoning = reasoning
        self._assembler = assembler

    async def run(
        self, task: str, *, parent: SessionKey, workspace_root: Path
    ) -> SubagentTask:
        """Start ``task`` and wait for the child turn to finish."""
        started = await self._spawn(task, parent, workspace_root, deliver=False)
        return await self.wait(started.id, parent=parent)

    async def start(
        self, task: str, *, parent: SessionKey, workspace_root: Path
    ) -> SubagentTask:
        """Start ``task`` in the background and return it while running.

        A background task delivers its reply to the origin conversation when
        it finishes, so the conversation learns about the result without
        polling.
        """
        return await self._spawn(task, parent, workspace_root, deliver=True)

    async def _spawn(
        self,
        task: str,
        parent: SessionKey,
        workspace_root: Path,
        *,
        deliver: bool,
    ) -> SubagentTask:
        if parent in self._children:
            raise ToolError("a subagent cannot delegate a further task")
        if self._reasoning is None or self._assembler is None:
            raise RuntimeError("subagent manager used before bind()")
        self._counter += 1
        task_id = f"{_TASK_PREFIX}{self._counter}"
        child = SessionKey(
            transport=parent.transport,
            conversation=f"{parent.conversation}:{_CHILD_MARKER}:{self._counter}",
        )
        record = _Running(
            id=task_id,
            parent=parent,
            child=child,
            deliver=deliver,
            sink=_RecordingSink(),
        )
        self._tasks[task_id] = record
        self._children.add(child)
        self._persist()
        record.handle = asyncio.create_task(
            self._execute(record, task, workspace_root)
        )
        return record.view()

    async def status(self, task_id: str, *, parent: SessionKey) -> SubagentTask:
        """Return one task's current state; only its origin may read it."""
        return self._owned(task_id, parent).view()

    async def wait(self, task_id: str, *, parent: SessionKey) -> SubagentTask:
        """Wait for one task to finish; only its origin may wait on it."""
        record = self._owned(task_id, parent)
        if record.handle is not None:
            await asyncio.gather(record.handle, return_exceptions=True)
        return record.view()

    async def cancel(self, task_id: str, *, parent: SessionKey) -> SubagentTask:
        """Cancel one task; only its origin may cancel it."""
        record = self._owned(task_id, parent)
        if record.handle is not None and not record.handle.done():
            record.handle.cancel()
            await asyncio.gather(record.handle, return_exceptions=True)
        return record.view()

    async def cancel_session(self, parent: SessionKey) -> tuple[SubagentTask, ...]:
        """Cancel every running task owned by ``parent``; return what stopped."""
        running = [
            record
            for record in self._tasks.values()
            if record.parent == parent
            and record.handle is not None
            and not record.handle.done()
        ]
        for record in running:
            if record.handle is not None:
                record.handle.cancel()
        if running:
            await asyncio.gather(
                *(record.handle for record in running if record.handle is not None),
                return_exceptions=True,
            )
        return tuple(record.view() for record in running)

    async def drain(self) -> None:
        """Wait for every running child so its result can be delivered."""
        handles = [
            record.handle
            for record in self._tasks.values()
            if record.handle is not None and not record.handle.done()
        ]
        if handles:
            await asyncio.gather(*handles, return_exceptions=True)

    async def shutdown(self) -> None:
        """Cancel every running child (called when the runtime closes)."""
        handles = [
            record.handle
            for record in self._tasks.values()
            if record.handle is not None and not record.handle.done()
        ]
        for handle in handles:
            handle.cancel()
        if handles:
            await asyncio.gather(*handles, return_exceptions=True)

    def _owned(self, task_id: str, parent: SessionKey) -> _Running:
        record = self._tasks.get(task_id)
        if record is None:
            raise ToolError(f"unknown subagent task {task_id!r}")
        if record.parent != parent:
            raise ToolError(
                f"subagent task {task_id!r} belongs to another conversation"
            )
        return record

    def _persist(self) -> None:
        if self._store is not None:
            self._store.save(tuple(record.record() for record in self._tasks.values()))

    async def _execute(
        self, record: _Running, task: str, workspace_root: Path
    ) -> None:
        reasoning = self._reasoning
        assembler = self._assembler
        if reasoning is None or assembler is None:
            record.status = SubagentStatus.FAILED
            record.text = "subagent manager used before bind()"
            self._persist()
            return
        sink = record.sink if record.sink is not None else _RecordingSink()
        task_message = Message(role=Role.USER, content=task)
        request = assembler.assemble((task_message,))

        async def _reason() -> ReasoningResult:
            return await reasoning.run(
                request,
                session=record.child,
                sink=sink,
                ctx=ToolContext(session=record.child, workspace_root=workspace_root),
                budget=self._budget,
            )

        try:
            if self._turns is None:
                result = await _reason()
            else:
                async with self._turns:
                    result = await _reason()
        except asyncio.CancelledError:
            record.text = sink.text
            record.status = SubagentStatus.CANCELLED
            self._persist()
            raise
        except NewbotError as exc:
            record.text = _combine(sink.text, str(exc))
            record.status = SubagentStatus.FAILED
            self._persist()
            return
        await self._sessions.record(record.child, (task_message, *result.produced))
        record.text = result.message.content
        record.status = (
            SubagentStatus.COMPLETED
            if result.status is TurnStatus.COMPLETED
            else SubagentStatus.INCOMPLETE
        )
        self._persist()
        if record.deliver:
            await self._deliver(record)

    async def _deliver(self, record: _Running) -> None:
        hub = self._hub
        if hub is None or not record.text:
            return
        try:
            await hub.publish(
                ResponseDelta(session=record.parent, text=record.text)
            )
            await hub.emit(
                OutboundEnvelope(
                    transport=record.parent.transport,
                    conversation_id=record.parent.conversation,
                    text=record.text,
                )
            )
        except NewbotError as exc:
            record.status = SubagentStatus.FAILED
            record.text = str(exc)
            self._persist()


def _ordinal(task_id: str) -> int:
    if not task_id.startswith(_TASK_PREFIX):
        return 0
    suffix = task_id[len(_TASK_PREFIX) :]
    return int(suffix) if suffix.isdigit() else 0


def _combine(partial: str, reason: str) -> str:
    if not partial:
        return reason
    return f"{partial}\n\n{reason}"
