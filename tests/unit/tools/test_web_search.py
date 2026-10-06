"""Contract tests for the web search tool and its registry/config wiring."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest
from pydantic import ValidationError

from newbot.config.schema import Settings
from newbot.domain.errors import ToolError
from newbot.domain.search import SearchResult
from newbot.domain.session import SessionKey
from newbot.policy.network import NetworkGuard
from newbot.policy.workspace import WorkspaceGuard
from newbot.ports.tools import ToolContext
from newbot.tools.registry import build_default_registry
from newbot.tools.web_search import WebSearchTool

CTX = ToolContext(session=SessionKey("cli", "default"), workspace_root=Path("."))


def _result(index: int) -> SearchResult:
    return SearchResult(
        title=f"title {index}",
        url=f"https://example.com/{index}",
        snippet=f"snippet {index}",
    )


class _StubSearch:
    def __init__(self, results: Sequence[SearchResult]) -> None:
        self._results = tuple(results)
        self.calls: list[tuple[str, int]] = []

    async def search(self, query: str, *, limit: int) -> tuple[SearchResult, ...]:
        self.calls.append((query, limit))
        return self._results[:limit]


async def test_search_formats_ranked_results() -> None:
    stub = _StubSearch([_result(1), _result(2)])

    result = await WebSearchTool(stub).invoke({"query": "hello"}, CTX)

    assert result.is_error is False
    assert "1. title 1" in result.text
    assert "https://example.com/1" in result.text
    assert "snippet 1" in result.text
    assert stub.calls == [("hello", 5)]


async def test_search_honors_an_explicit_max_results() -> None:
    stub = _StubSearch([_result(1), _result(2), _result(3)])

    result = await WebSearchTool(stub).invoke(
        {"query": "q", "max_results": 2}, CTX
    )

    assert "3. title 3" not in result.text
    assert stub.calls == [("q", 2)]


async def test_search_rejects_an_invalid_max_results() -> None:
    with pytest.raises(ToolError, match="max_results"):
        await WebSearchTool(_StubSearch([])).invoke(
            {"query": "q", "max_results": 0}, CTX
        )


async def test_search_requires_a_query() -> None:
    with pytest.raises(ToolError):
        await WebSearchTool(_StubSearch([])).invoke({}, CTX)


async def test_search_reports_no_results() -> None:
    result = await WebSearchTool(_StubSearch([])).invoke({"query": "q"}, CTX)

    assert result.text == "no results"


def test_web_tools_are_gated_by_config(tmp_path: Path) -> None:
    enabled = build_default_registry(
        WorkspaceGuard(tmp_path),
        network_guard=NetworkGuard(),
        web_search=WebSearchTool(_StubSearch([])),
    )
    assert {"web_fetch", "web_search"} <= {spec.name for spec in enabled.specs()}

    disabled = build_default_registry(
        WorkspaceGuard(tmp_path), network_guard=NetworkGuard(), enable_web=False
    )
    names = {spec.name for spec in disabled.specs()}
    assert "web_fetch" not in names
    assert "web_search" not in names


def test_web_search_config_defaults_and_rejects_unknown_providers() -> None:
    settings = Settings.model_validate(
        {
            "provider": {"baseUrl": "https://api.example.com/v1"},
            "agent": {"model": "m"},
        }
    )
    assert settings.tools.web.enable is True
    assert settings.tools.web.search.provider == "duckduckgo"
    assert settings.tools.web.search.max_results == 5

    with pytest.raises(ValidationError):
        Settings.model_validate(
            {
                "provider": {"baseUrl": "https://api.example.com/v1"},
                "agent": {"model": "m"},
                "tools": {"web": {"search": {"provider": "brave"}}},
            }
        )
