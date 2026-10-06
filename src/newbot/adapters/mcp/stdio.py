"""Stdio MCP client: launch one server and speak newline-delimited JSON-RPC."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from collections import deque
from collections.abc import Mapping

from newbot import __version__
from newbot.adapters.mcp.protocol import describe_error, tool_result, tool_specs
from newbot.domain.errors import McpError
from newbot.domain.mcp import (
    MCP_PROTOCOL_VERSION,
    McpStdioServerSpec,
    McpToolResult,
    McpToolSpec,
)

_REQUEST_TIMEOUT_SECONDS = 30.0
_SHUTDOWN_TIMEOUT_SECONDS = 5.0
_CLIENT_NAME = "newbot"
_STDERR_TAIL_LINES = 20


class StdioMcpClient:
    """Owns one stdio MCP server process and its JSON-RPC session.

    The server is started once and reused for every ``list_tools``/``call_tool``
    request; requests are serialized so concurrent turns cannot interleave a
    request and its response on the shared pipe. Every message the server sends
    is parsed at the boundary, so a malformed reply is a typed ``McpError``
    rather than a crash.
    """

    def __init__(
        self, spec: McpStdioServerSpec, *, timeout: float = _REQUEST_TIMEOUT_SECONDS
    ) -> None:
        self._spec = spec
        self._timeout = timeout
        self._process: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self._next_id = 0
        self._stderr_tail: deque[str] = deque(maxlen=_STDERR_TAIL_LINES)
        self._stderr_task: asyncio.Task[None] | None = None

    @property
    def server(self) -> str:
        return self._spec.name

    async def start(self) -> None:
        """Launch the server and complete the MCP initialize handshake."""
        env = dict(os.environ)
        env.update(self._spec.env)
        try:
            self._process = await asyncio.create_subprocess_exec(
                self._spec.command,
                *self._spec.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except OSError as exc:
            raise McpError(
                f"mcp server {self._spec.name!r} could not start: {exc}"
            ) from exc
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        try:
            await self._request(
                "initialize",
                {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": _CLIENT_NAME, "version": __version__},
                },
            )
            await self._notify("notifications/initialized", {})
        except McpError:
            await self.aclose()
            raise

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
        """Terminate the server and stop draining its stderr; idempotent."""
        process, self._process = self._process, None
        task, self._stderr_task = self._stderr_task, None
        try:
            if process is not None and process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(
                        process.wait(), timeout=_SHUTDOWN_TIMEOUT_SECONDS
                    )
                except TimeoutError:
                    process.kill()
                    await process.wait()
        finally:
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    async def _request(self, method: str, params: Mapping[str, object]) -> object:
        async with self._lock:
            process = self._require_process()
            self._next_id += 1
            request_id = self._next_id
            await self._write(
                process,
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params,
                },
            )
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self._timeout
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise McpError(
                        f"mcp server {self._spec.name!r} did not answer {method} "
                        f"within {self._timeout:g}s"
                    )
                message = await self._read(process, timeout=remaining)
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

    async def _notify(self, method: str, params: Mapping[str, object]) -> None:
        async with self._lock:
            await self._write(
                self._require_process(),
                {"jsonrpc": "2.0", "method": method, "params": params},
            )

    async def _write(
        self, process: asyncio.subprocess.Process, payload: Mapping[str, object]
    ) -> None:
        if process.stdin is None:
            raise McpError(f"mcp server {self._spec.name!r} has no input pipe")
        try:
            process.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
            await process.stdin.drain()
        except OSError as exc:
            raise McpError(
                f"mcp server {self._spec.name!r} closed its input: {exc}"
            ) from exc

    async def _read(
        self, process: asyncio.subprocess.Process, *, timeout: float
    ) -> dict[str, object]:
        if process.stdout is None:
            raise McpError(f"mcp server {self._spec.name!r} has no output pipe")
        try:
            raw = await asyncio.wait_for(
                process.stdout.readline(), timeout=timeout
            )
        except TimeoutError as exc:
            raise McpError(
                f"mcp server {self._spec.name!r} did not answer within "
                f"{timeout:g}s"
            ) from exc
        if not raw:
            raise McpError(
                f"mcp server {self._spec.name!r} closed its output"
                f"{self._stderr_suffix()}"
            )
        try:
            message = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise McpError(
                f"mcp server {self._spec.name!r} sent invalid JSON"
            ) from exc
        if not isinstance(message, dict):
            raise McpError(
                f"mcp server {self._spec.name!r} sent a non-object message"
            )
        return message

    async def _drain_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        async for raw in process.stderr:
            line = raw.decode("utf-8", errors="replace").rstrip()
            if line:
                self._stderr_tail.append(line)

    def _require_process(self) -> asyncio.subprocess.Process:
        process = self._process
        if process is None:
            raise McpError(f"mcp server {self._spec.name!r} is not running")
        return process

    def _stderr_suffix(self) -> str:
        if not self._stderr_tail:
            return ""
        return "; stderr:\n" + "\n".join(self._stderr_tail)
