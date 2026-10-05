"""The provider interface the reasoning loop depends on."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from newbot.domain.provider import ModelRequest, StreamEvent


class ProviderPort(Protocol):
    """A streaming language-model backend."""

    def stream(self, request: ModelRequest) -> AsyncIterator[StreamEvent]:
        """Yield text deltas, then exactly one ``Completed`` event."""
        ...

    async def aclose(self) -> None:
        """Release resources held by the provider."""
        ...
