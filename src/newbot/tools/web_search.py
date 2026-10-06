"""Guarded web search tool (S3)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from newbot.domain.errors import ToolError
from newbot.domain.search import SearchResult
from newbot.domain.tool import ToolSpec
from newbot.ports.search import SearchPort
from newbot.ports.tools import ToolContext
from newbot.tools.base import ToolOutput, require_string

DEFAULT_MAX_RESULTS = 5
_MAX_RESULTS_LIMIT = 20

_SCHEMA: Mapping[str, object] = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "The search query."},
        "max_results": {
            "type": "integer",
            "minimum": 1,
            "maximum": _MAX_RESULTS_LIMIT,
            "description": "How many results to return.",
        },
    },
    "required": ["query"],
    "additionalProperties": False,
}


class WebSearchTool:
    """Searches the public web through a configured backend."""

    def __init__(
        self, search: SearchPort, *, default_max_results: int = DEFAULT_MAX_RESULTS
    ) -> None:
        self._search = search
        self._default_max_results = default_max_results
        self.spec = ToolSpec(
            name="web_search",
            description="Search the public web and return ranked results with URLs.",
            parameters=_SCHEMA,
        )

    async def invoke(
        self, arguments: Mapping[str, object], ctx: ToolContext
    ) -> ToolOutput:
        query = require_string(arguments, "query")
        limit = _max_results(arguments, self._default_max_results)
        results = await self._search.search(query, limit=limit)
        if not results:
            return ToolOutput(text="no results")
        return ToolOutput(text=_render(results))


def _max_results(arguments: Mapping[str, object], default: int) -> int:
    value = arguments.get("max_results")
    if value is None:
        return default
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= _MAX_RESULTS_LIMIT
    ):
        raise ToolError(
            f"argument 'max_results' must be an integer between 1 and {_MAX_RESULTS_LIMIT}"
        )
    return value


def _render(results: Sequence[SearchResult]) -> str:
    blocks: list[str] = []
    for index, result in enumerate(results, start=1):
        block = f"{index}. {result.title}\n   {result.url}"
        if result.snippet:
            block += f"\n   {result.snippet}"
        blocks.append(block)
    return "\n\n".join(blocks)
