"""Contract tests for the DuckDuckGo search backend."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from newbot.adapters.search.duckduckgo import DuckDuckGoSearch
from newbot.domain.errors import NetworkAccessDenied, ToolError
from newbot.policy.network import NetworkGuard

_PUBLIC = "93.184.216.34"

_HTML = """
<html><body>
<div class="result results_links">
  <a rel="nofollow" class="result__a"
     href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fone&rut=x">First &amp; Result</a>
  <a class="result__snippet"
     href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fone">The <b>first</b> snippet.</a>
</div>
<div class="result results_links">
  <a class="result__a" href="https://second.example/two">Second</a>
  <a class="result__snippet">Second snippet.</a>
</div>
<div class="result results_links">
  <a class="result__a" href="https://third.example/three">Third</a>
</div>
</body></html>
"""


def _guard() -> NetworkGuard:
    async def resolve(host: str) -> tuple[str, ...]:
        return (_PUBLIC,)

    return NetworkGuard(resolver=resolve)


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_parses_titles_urls_and_snippets() -> None:
    results = await DuckDuckGoSearch(
        _guard(), client=_client(lambda request: httpx.Response(200, text=_HTML))
    ).search("q", limit=5)

    assert [result.title for result in results] == ["First & Result", "Second", "Third"]
    assert [result.url for result in results] == [
        "https://example.com/one",
        "https://second.example/two",
        "https://third.example/three",
    ]
    assert results[0].snippet == "The first snippet."
    assert results[1].snippet == "Second snippet."
    assert results[2].snippet == ""


async def test_pins_the_request_to_the_validated_address() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text=_HTML)

    await DuckDuckGoSearch(_guard(), client=_client(handler)).search(
        "hello world", limit=3
    )

    assert seen[0].url.host == _PUBLIC
    assert seen[0].headers["host"] == "html.duckduckgo.com"
    assert seen[0].url.params.get("q") == "hello world"


async def test_respects_the_limit() -> None:
    results = await DuckDuckGoSearch(
        _guard(), client=_client(lambda request: httpx.Response(200, text=_HTML))
    ).search("q", limit=1)

    assert [result.title for result in results] == ["First & Result"]


async def test_follows_a_redirect() -> None:
    paths: list[str] = []
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        paths.append(request.url.path)
        calls += 1
        if calls == 1:
            return httpx.Response(302, headers={"location": "/html/?q=x"})
        return httpx.Response(200, text=_HTML)

    results = await DuckDuckGoSearch(_guard(), client=_client(handler)).search(
        "x", limit=5
    )

    assert len(results) == 3
    assert paths == ["/html/", "/html/"]


async def test_rejects_a_blocked_address() -> None:
    async def resolve(host: str) -> tuple[str, ...]:
        return ("127.0.0.1",)

    client = _client(lambda request: httpx.Response(200, text=""))
    with pytest.raises(NetworkAccessDenied):
        await DuckDuckGoSearch(NetworkGuard(resolver=resolve), client=client).search(
            "q", limit=1
        )


async def test_reports_an_error_status() -> None:
    client = _client(lambda request: httpx.Response(503, text="nope"))

    with pytest.raises(ToolError, match="HTTP 503"):
        await DuckDuckGoSearch(_guard(), client=client).search("q", limit=1)
