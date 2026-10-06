"""HTTP MCP client: speak JSON-RPC over the streamable-HTTP transport."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping

import httpx

from newbot import __version__
from newbot.adapters.mcp.protocol import describe_error, tool_result, tool_specs
from newbot.domain.errors import McpError
from newbot.domain.mcp import (
    MCP_PROTOCOL_VERSION,
    McpHttpServerSpec,
    McpToolResult,
    McpToolSpec,
)
from newbot.policy.network import NetworkGuard, PinnedTarget

_REQUEST_TIMEOUT_SECONDS = 30.0
_CLIENT_NAME = "newbot"
_SSE_CONTENT_TYPE = "text/event-stream"


class HttpMcpClient:
    """Owns one HTTP MCP session, validating and pinning every request.

    The configured URL is resolved through the network guard before each
    request and the connection is pinned to the validated address, so a
    rebinding resolver cannot redirect it. The streamable-HTTP transport is
    POST-only: a reply arrives either as one JSON object or as an SSE stream,
    and a server-assigned ``Mcp-Session-Id`` is echoed on every later request.
    """

    def __init__(
        self,
        spec: McpHttpServerSpec,
        guard: NetworkGuard,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = _REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self._spec = spec
        self._guard = guard
        self._timeout = timeout
        self._client = client
        self._owns_client = client is None
        self._session_id: str | None = None
        self._next_id = 0
        self._lock = asyncio.Lock()

    @property
    def server(self) -> str:
        return self._spec.name

    async def start(self) -> None:
        """Open the client and complete the MCP initialize handshake."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        await self._request(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": _CLIENT_NAME, "version": __version__},
            },
        )
        await self._notify("notifications/initialized", {})

    async def list_tools(self) -> tuple[McpToolSpec, ...]:
        """Return the tools the server advertises, validated at the boundary."""
        return tool_specs(self._spec.name, await self._request("tools/list", {}))

    async def call_tool(
        self, name: str, arguments: Mapping[str, object]
    ) -> McpToolResult:
        """Invoke one remote tool and normalize its content blocks."""
        return tool_result(
            self._spec.name,
            await self._request(
                "tools/call", {"name": name, "arguments": dict(arguments)}
            ),
        )

    async def aclose(self) -> None:
        """Close the HTTP client this instance owns; idempotent."""
        client, self._client = self._client, None
        if client is not None and self._owns_client:
            await client.aclose()

    async def _request(self, method: str, params: Mapping[str, object]) -> object:
        async with self._lock:
            self._next_id += 1
            request_id = self._next_id
            messages = await self._post(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params,
                }
            )
            for message in messages:
                if message.get("id") != request_id:
                    continue
                error = message.get("error")
                if error is not None:
                    raise McpError(
                        f"mcp server {self._spec.name!r} {method} failed: "
                        f"{describe_error(error)}"
                    )
                if "result" not in message:
                    raise McpError(
                        f"mcp server {self._spec.name!r} {method} returned no result"
                    )
                return message["result"]
            raise McpError(f"mcp server {self._spec.name!r} did not answer {method}")

    async def _notify(self, method: str, params: Mapping[str, object]) -> None:
        async with self._lock:
            await self._post(
                {"jsonrpc": "2.0", "method": method, "params": params},
                notification=True,
            )

    async def _post(
        self, payload: Mapping[str, object], *, notification: bool = False
    ) -> list[dict[str, object]]:
        target = await self._guard.resolve(self._spec.url)
        headers = {
            "Host": _host_header(self._spec.url),
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if self._session_id is not None:
            headers["Mcp-Session-Id"] = self._session_id
        try:
            response = await self._require_client().post(
                target.connect_url,
                headers=headers,
                extensions=_tls_extensions(target),
                content=json.dumps(payload),
            )
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            raise McpError(
                f"mcp server {self._spec.name!r} request failed: {exc}"
            ) from exc
        session = response.headers.get("Mcp-Session-Id")
        if session:
            self._session_id = session
        if response.status_code == 202:
            if notification:
                return []
            raise McpError(
                f"mcp server {self._spec.name!r} accepted the request without "
                "answering"
            )
        if not response.is_success:
            raise McpError(
                f"mcp server {self._spec.name!r} rejected the request with "
                f"HTTP {response.status_code}"
            )
        content_type = response.headers.get("Content-Type", "")
        if content_type.split(";", 1)[0].strip().lower() == _SSE_CONTENT_TYPE:
            return _parse_sse(self._spec.name, response.text)
        return _parse_json_body(self._spec.name, response.text)

    def _require_client(self) -> httpx.AsyncClient:
        client = self._client
        if client is None:
            raise McpError(f"mcp server {self._spec.name!r} is not running")
        return client


def _host_header(url: str) -> str:
    """The ``Host`` header httpx derives for the original URL."""
    return httpx.URL(url).netloc.decode("ascii")


def _tls_extensions(target: PinnedTarget) -> dict[str, str]:
    if target.scheme == "https":
        return {"sni_hostname": target.host}
    return {}


def _parse_json_body(server: str, text: str) -> list[dict[str, object]]:
    if not text.strip():
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise McpError(f"mcp server {server!r} sent invalid JSON") from exc
    return _as_messages(server, data)


def _parse_sse(server: str, text: str) -> list[dict[str, object]]:
    messages: list[dict[str, object]] = []
    data_lines: list[str] = []
    for line in text.splitlines():
        if line == "":
            if data_lines:
                messages.append(_load_message(server, "\n".join(data_lines)))
                data_lines = []
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        if field == "data":
            data_lines.append(value[1:] if value.startswith(" ") else value)
    if data_lines:
        messages.append(_load_message(server, "\n".join(data_lines)))
    return messages


def _load_message(server: str, text: str) -> dict[str, object]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise McpError(f"mcp server {server!r} sent invalid JSON") from exc
    return _as_message(server, data)


def _as_messages(server: str, data: object) -> list[dict[str, object]]:
    if isinstance(data, list):
        return [_as_message(server, item) for item in data]
    return [_as_message(server, data)]


def _as_message(server: str, data: object) -> dict[str, object]:
    if not isinstance(data, dict):
        raise McpError(f"mcp server {server!r} sent a non-object message")
    return data
