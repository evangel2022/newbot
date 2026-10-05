"""The model-facing reasoning loop."""

from __future__ import annotations

from dataclasses import dataclass, replace

from newbot.domain.errors import ProviderError
from newbot.domain.events import ResponseDelta
from newbot.domain.message import Message, Role
from newbot.domain.provider import Completed, ModelRequest, TextDelta
from newbot.domain.session import SessionKey
from newbot.domain.turn import Budget, TurnStatus
from newbot.ports.events import EventSink
from newbot.ports.provider import ProviderPort
from newbot.ports.tools import ToolContext, ToolRegistryPort


@dataclass(frozen=True, slots=True)
class ReasoningResult:
    """The outcome of one turn's reasoning."""

    message: Message
    produced: tuple[Message, ...]
    status: TurnStatus


class ReasoningLoop:
    """Calls the provider, streams deltas, dispatches tools, and bounds iterations."""

    def __init__(self, provider: ProviderPort, registry: ToolRegistryPort) -> None:
        self._provider = provider
        self._registry = registry

    async def run(
        self,
        request: ModelRequest,
        *,
        session: SessionKey,
        sink: EventSink,
        ctx: ToolContext,
        budget: Budget,
    ) -> ReasoningResult:
        """Run the bounded model/tool loop for one turn."""
        messages = list(request.messages)
        produced: list[Message] = []
        message = await self._call_provider(
            replace(request, messages=tuple(messages)), session, sink
        )
        iterations = 1
        while message.tool_calls:
            if iterations >= budget.max_iterations:
                return ReasoningResult(
                    message=message,
                    produced=tuple(produced),
                    status=TurnStatus.BUDGET_EXCEEDED,
                )
            messages.append(message)
            produced.append(message)
            for tool_call in message.tool_calls:
                result = await self._registry.invoke(tool_call, ctx)
                tool_message = Message(
                    role=Role.TOOL,
                    content=result.content,
                    tool_call_id=result.call_id,
                )
                messages.append(tool_message)
                produced.append(tool_message)
            message = await self._call_provider(
                replace(request, messages=tuple(messages)), session, sink
            )
            iterations += 1
        produced.append(message)
        return ReasoningResult(
            message=message, produced=tuple(produced), status=TurnStatus.COMPLETED
        )

    async def _call_provider(
        self, request: ModelRequest, session: SessionKey, sink: EventSink
    ) -> Message:
        final: Message | None = None
        async for event in self._provider.stream(request):
            if isinstance(event, TextDelta):
                await sink.publish(ResponseDelta(session=session, text=event.text))
            elif isinstance(event, Completed):
                final = event.message
        if final is None:
            raise ProviderError("provider stream ended without a completion")
        return final
