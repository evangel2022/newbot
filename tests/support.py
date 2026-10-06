"""Shared in-memory fakes for tests. Depends only on public newbot types."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import datetime

from newbot.domain.curation import CurationEdit, DurableFile
from newbot.domain.envelope import OutboundEnvelope
from newbot.domain.errors import ProviderError, TransportError
from newbot.domain.events import AgentEvent
from newbot.domain.job import ScheduledJob
from newbot.domain.journal import JournalEntry
from newbot.domain.message import Message, Role
from newbot.domain.provider import Completed, ModelRequest, StreamEvent, TextDelta
from newbot.domain.session import SessionKey, SessionRecord
from newbot.domain.tool import ToolCall, ToolResult, ToolSpec
from newbot.ports.tools import ToolContext


def reply_events(text: str, *, chunk_size: int = 4) -> list[StreamEvent]:
    """Build a text stream that ends with an authoritative completion."""
    events: list[StreamEvent] = [
        TextDelta(text=text[index : index + chunk_size])
        for index in range(0, len(text), chunk_size)
    ]
    events.append(Completed(message=Message(role=Role.ASSISTANT, content=text)))
    return events


class FakeProvider:
    """A scripted provider that replays the same events for every request."""

    def __init__(self, events: Sequence[StreamEvent]) -> None:
        self._events = list(events)
        self.requests: list[ModelRequest] = []
        self.closed = False

    def stream(self, request: ModelRequest) -> AsyncIterator[StreamEvent]:
        self.requests.append(request)
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[StreamEvent]:
        for event in self._events:
            yield event

    async def aclose(self) -> None:
        self.closed = True


class FailingProvider:
    """A provider whose stream raises a deliberate error."""

    def stream(self, request: ModelRequest) -> AsyncIterator[StreamEvent]:
        return _boom()

    async def aclose(self) -> None:
        return None


class FailingTransport:
    """A transport whose outbound delivery always fails."""

    transport_id = "test"

    def __init__(self) -> None:
        self.delivered: list[OutboundEnvelope] = []

    async def deliver(self, envelope: OutboundEnvelope) -> None:
        self.delivered.append(envelope)
        raise TransportError("transport down")


async def _boom() -> AsyncIterator[StreamEvent]:
    raise ProviderError("provider down")
    yield TextDelta(text="unreachable")


class ConcurrencyTrackingProvider:
    """Reports the maximum number of concurrently active streams."""

    def __init__(self) -> None:
        self.active = 0
        self.max_concurrent = 0

    def stream(self, request: ModelRequest) -> AsyncIterator[StreamEvent]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[StreamEvent]:
        self.active += 1
        self.max_concurrent = max(self.max_concurrent, self.active)
        try:
            await asyncio.sleep(0.01)
            yield Completed(message=Message(role=Role.ASSISTANT, content="ok"))
        finally:
            self.active -= 1

    async def aclose(self) -> None:
        return None


class RecordingSink:
    """Collects agent events."""

    def __init__(self) -> None:
        self.events: list[AgentEvent] = []

    async def publish(self, event: AgentEvent) -> None:
        self.events.append(event)


class CollectingTransport:
    """Collects delivered outbound envelopes and, optionally, events."""

    transport_id = "test"

    def __init__(self) -> None:
        self.delivered: list[OutboundEnvelope] = []
        self.events: list[AgentEvent] = []

    async def deliver(self, envelope: OutboundEnvelope) -> None:
        self.delivered.append(envelope)

    async def publish(self, event: AgentEvent) -> None:
        self.events.append(event)


class ScriptedProvider:
    """Yields one scripted assistant message per stream call, in order."""

    def __init__(self, messages: Sequence[Message]) -> None:
        self._messages = list(messages)
        self.requests: list[ModelRequest] = []

    def stream(self, request: ModelRequest) -> AsyncIterator[StreamEvent]:
        self.requests.append(request)
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[StreamEvent]:
        message = self._messages.pop(0)
        if message.content:
            yield TextDelta(text=message.content)
        yield Completed(message=message)

    async def aclose(self) -> None:
        return None


class StubRegistry:
    """A ``ToolRegistryPort`` stub returning preconfigured results."""

    def __init__(
        self,
        *,
        specs: Sequence[ToolSpec] = (),
        results: Mapping[str, ToolResult] | None = None,
    ) -> None:
        self._specs = tuple(specs)
        self._results = dict(results or {})
        self.calls: list[ToolCall] = []

    def specs(self) -> tuple[ToolSpec, ...]:
        return self._specs

    async def invoke(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        self.calls.append(call)
        return self._results.get(
            call.name, ToolResult(call_id=call.id, content=f"ran {call.name}")
        )


class MemorySessionStore:
    """In-memory ``SessionStorePort`` for unit tests."""

    def __init__(self) -> None:
        self.records: dict[tuple[str, str, str], list[SessionRecord]] = {}

    async def load(
        self, workspace_id: str, key: SessionKey
    ) -> tuple[SessionRecord, ...]:
        bucket = self.records.get((workspace_id, key.transport, key.conversation), [])
        return tuple(bucket)

    async def append(
        self, workspace_id: str, key: SessionKey, records: Sequence[SessionRecord]
    ) -> None:
        bucket = self.records.setdefault(
            (workspace_id, key.transport, key.conversation), []
        )
        bucket.extend(records)

    async def rewrite(
        self, workspace_id: str, key: SessionKey, records: Sequence[SessionRecord]
    ) -> None:
        self.records[(workspace_id, key.transport, key.conversation)] = list(records)


class MemoryJobStore:
    """In-memory ``JobStorePort`` for unit tests."""

    def __init__(self) -> None:
        self._items: list[ScheduledJob] = []

    def jobs(self) -> tuple[ScheduledJob, ...]:
        return tuple(self._items)

    def add(
        self,
        *,
        transport: str,
        conversation: str,
        prompt: str,
        next_run_at: datetime,
        every_seconds: float | None = None,
    ) -> ScheduledJob:
        job = ScheduledJob(
            id=f"job-{len(self._items) + 1}",
            transport=transport,
            conversation=conversation,
            prompt=prompt,
            next_run_at=next_run_at,
            every_seconds=every_seconds,
        )
        self._items.append(job)
        return job

    def remove(self, job_id: str) -> bool:
        kept = [job for job in self._items if job.id != job_id]
        if len(kept) == len(self._items):
            return False
        self._items = kept
        return True


class FakeSummarizer:
    """A ``SummarizerPort`` stub that records its input and returns one summary."""

    def __init__(self, summary: str = "summary") -> None:
        self._summary = summary
        self.inputs: list[tuple[Message, ...]] = []

    async def summarize(self, messages: Sequence[Message]) -> str:
        self.inputs.append(tuple(messages))
        return self._summary


class ScriptedCurator:
    """A ``CurationPort`` stub that records its input and replays fixed edits."""

    def __init__(self, edits: Sequence[CurationEdit] = ()) -> None:
        self._edits = tuple(edits)
        self.calls: list[tuple[tuple[JournalEntry, ...], tuple[DurableFile, ...]]] = []

    async def interpret(
        self, entries: Sequence[JournalEntry], files: Sequence[DurableFile]
    ) -> tuple[CurationEdit, ...]:
        self.calls.append((tuple(entries), tuple(files)))
        return self._edits
