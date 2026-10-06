"""The web search provider interface."""

from __future__ import annotations

from typing import Protocol

from newbot.domain.search import SearchResult


class SearchPort(Protocol):
    """Queries a search backend and returns ranked results."""

    async def search(self, query: str, *, limit: int) -> tuple[SearchResult, ...]:
        """Return at most ``limit`` results for ``query``."""
        ...
