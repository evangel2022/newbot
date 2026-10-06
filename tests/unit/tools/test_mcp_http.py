"""Contract tests for the HTTP MCP client; the server is an httpx mock."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence

import httpx
import pytest

from newbot.adapters.mcp.http import HttpMcpClient
from newbot.domain.errors import McpError, NetworkAccessDenied
from newbot.domain.mcp import McpHttpServerSpec
from newbot.policy.network import NetworkGuard

_PUBLIC = "93.184.216.34"
_URL = "https://mcp.example.com/mcp"


def _guard() -> NetworkGuard:
    async def resolve(host: str) -> Sequence[str]:
        return (_PUBLIC,)

    return NetworkGuard(resolver=resolve)


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _jsonrpc(
    request_id: object, result: object, *, session: str | None = None
) -> httpx.Response:
    headers = {"Content-Type": "application/json"}
    if session is not None:
        headers["Mcp-Session-Id"] = session
    return httpx.Response(
        200,
        json={"jsonrpc": "2.0", "id": request_id, "result": result},
        headers=headers,
    )


async def test_initializes_lists_and_calls_over_pinned_requests() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        payload = json.loads(request.content)
        method = payload["method"]
        if method == "initialize":
            return _jsonrpc(
                payload["id"], {"protocolVersion": "2024-11-05"}, session="session-1"
            )
        if method == "notifications/initialized":
            return httpx.Response(202)
        if method == "tools/list":
            return _jsonrpc(
                payload["id"],
                {
                    "tools": [
                        {
                            "name": "echo",
                            "description": "Echo.",
                            "inputSchema": {"type": "object"},
                        }
                    ]
                },
            )
        if method == "tools/call":
            return _jsonrpc(
                payload["id"],
                {
                    "content": [{"type": "text", "text": "echo: hi"}],
                    "isError": False,
                },
            )
        raise AssertionError(f"unexpected method {method}")

    client = HttpMcpClient(
        McpHttpServerSpec(name="remote", url=_URL), _guard(), client=_client(handler)
    )
    await client.start()
    try:
        tools = await client.list_tools()
        assert [tool.name for tool in tools] == ["echo"]
        assert tools[0].parameters == {"type": "object"}

        result = await client.call_tool("echo", {"text": "hi"})
        assert result.text == "echo: hi"
        assert result.is_error is False
    finally:
        await client.aclose()

    assert seen[0].url.host == _PUBLIC
    assert seen[0].headers["host"] == "mcp.example.com"
    assert seen[0].headers["content-type"] == "application/json"
    assert "text/event-stream" in seen[0].headers["accept"]
    assert seen[1].headers["mcp-session-id"] == "session-1"
    assert seen[-1].headers["mcp-session-id"] == "session-1"


async def test_reads_a_result_from_an_sse_stream() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        if payload["method"] == "initialize":
            return _jsonrpc(payload["id"], {"protocolVersion": "2024-11-05"})
        if payload["method"] == "notifications/initialized":
            return httpx.Response(202)
        message = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {"tools": [{"name": "echo"}]},
            }
        )
        return httpx.Response(
            200,
            text=f"event: message\ndata: {message}\n\n",
            headers={"Content-Type": "text/event-stream"},
        )

    client = HttpMcpClient(
        McpHttpServerSpec(name="remote", url=_URL), _guard(), client=_client(handler)
    )
    await client.start()
    try:
        tools = await client.list_tools()
    finally:
        await client.aclose()

    assert [tool.name for tool in tools] == ["echo"]


async def test_a_jsonrpc_error_is_a_typed_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        if payload["method"] == "notifications/initialized":
            return httpx.Response(202)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": payload["id"],
                "error": {"code": -32601, "message": "no such method"},
            },
            headers={"Content-Type": "application/json"},
        )

    client = HttpMcpClient(
        McpHttpServerSpec(name="remote", url=_URL), _guard(), client=_client(handler)
    )

    with pytest.raises(McpError) as info:
        await client.start()

    assert "no such method" in str(info.value)


async def test_a_rejected_post_is_a_typed_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(405)

    client = HttpMcpClient(
        McpHttpServerSpec(name="remote", url=_URL), _guard(), client=_client(handler)
    )

    with pytest.raises(McpError) as info:
        await client.start()

    assert "405" in str(info.value)


async def test_a_transport_failure_is_a_typed_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    client = HttpMcpClient(
        McpHttpServerSpec(name="remote", url=_URL), _guard(), client=_client(handler)
    )

    with pytest.raises(McpError):
        await client.start()


async def test_a_private_target_is_blocked_before_the_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("the guard must block before any request")

    client = HttpMcpClient(
        McpHttpServerSpec(name="remote", url="http://127.0.0.1/mcp"),
        NetworkGuard(),
        client=_client(handler),
    )

    with pytest.raises(NetworkAccessDenied):
        await client.start()
