"""Value types for web search results."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SearchResult:
    """One ranked web search result."""

    title: str
    url: str
    snippet: str
