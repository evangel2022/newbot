"""Summarizer that condenses messages with one provider call."""

from __future__ import annotations

from collections.abc import Sequence

from newbot.domain.errors import ProviderError
from newbot.domain.message import Message
from newbot.domain.provider import Completed, ModelRequest
from newbot.ports.provider import ProviderPort

_PROMPT = (
    "You compress agent conversation history. Summarize the messages below into a "
    "concise brief that preserves decisions, facts, file paths, and unfinished work. "
    "Reply with the summary only."
)


class ProviderSummarizer:
    """Turns a run of messages into a checkpoint summary via the provider."""

    def __init__(self, provider: ProviderPort, *, model: str) -> None:
        self._provider = provider
        self._model = model

    async def summarize(self, messages: Sequence[Message]) -> str:
        request = ModelRequest(
            model=self._model, system=_PROMPT, messages=tuple(messages)
        )
        final: Message | None = None
        async for event in self._provider.stream(request):
            if isinstance(event, Completed):
                final = event.message
        if final is None:
            raise ProviderError("provider stream ended without a completion")
        return final.content
