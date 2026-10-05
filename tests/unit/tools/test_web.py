"""Contract tests for the guarded web fetch tool."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

import httpx
import pytest

from newbot.domain.errors import NetworkAccessDenied, ToolError
from newbot.domain.session import SessionKey
from newbot.policy.network import NetworkGuard
from newbot.ports.tools import ToolContext
from newbot.tools.web import WebFetchTool

_PUBLIC = "93.184.216.34"
CTX = ToolContext(session=SessionKey("t", "c"), workspace_root=Path("."))


def _guard() -> NetworkGuard:
    async def resolve(host: str) -> Sequence[str]:
        return (_PUBLIC,)

    return NetworkGuard(resolver=resolve)


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_fetches_text_from_a_public_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="hello world")

    result = await WebFetchTool(_guard(), client=_client(handler)).invoke(
        {"url": "https://example.com/"}, CTX
    )

    assert result.is_error is False
    assert result.text == "hello world"


async def test_follows_a_redirect_to_a_public_target() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(301, headers={"location": "/final"})
        return httpx.Response(200, text="landed")

    result = await WebFetchTool(_guard(), client=_client(handler)).invoke(
        {"url": "https://example.com/start"}, CTX
    )

    assert result.text == "landed"


async def test_redirect_to_a_private_target_is_blocked() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://169.254.169.254/"})

    with pytest.raises(NetworkAccessDenied):
        await WebFetchTool(_guard(), client=_client(handler)).invoke(
            {"url": "https://example.com/start"}, CTX
        )


async def test_http_error_status_is_an_error_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="nope")

    result = await WebFetchTool(_guard(), client=_client(handler)).invoke(
        {"url": "https://example.com/missing"}, CTX
    )

    assert result.is_error is True
    assert "404" in result.text


async def test_transport_failure_becomes_a_tool_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    with pytest.raises(ToolError):
        await WebFetchTool(_guard(), client=_client(handler)).invoke(
            {"url": "https://example.com/"}, CTX
        )
