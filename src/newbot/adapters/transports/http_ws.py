"""Loopback HTTP workbench: health, capability negotiation, turns, and streaming."""

from __future__ import annotations

import asyncio
import contextlib
import http.server
import io
import json
import queue
import secrets
import select
import socket
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from newbot.adapters.transports.websocket import (
    MAX_MESSAGE_BYTES,
    WebSocketConnection,
    WebSocketError,
    accept_key,
)
from newbot.domain.envelope import InboundEnvelope, OutboundEnvelope
from newbot.domain.errors import TransportError
from newbot.domain.events import (
    AgentEvent,
    ResponseDelta,
    TurnCompleted,
    TurnFailed,
    TurnStarted,
)
from newbot.policy.access import AccessPolicy
from newbot.ports.transports import InboundHandler

WORKBENCH_PROTOCOL = 1
WORKBENCH_TRANSPORT_ID = "webui"
CAPABILITIES: tuple[str, ...] = ("chat", "stream", "ticket")

_LOOPBACK = "127.0.0.1"
_REPLY_TIMEOUT = 120.0
_STREAM_PATH = "/stream"
_TICKET_PATH = "/ticket"
_STREAM_POLL_SECONDS = 0.05
_MAX_CONVERSATION_CHARS = 200
_TICKET_PROTOCOL_PREFIX = "newbot.ticket."
_TICKET_TTL_SECONDS = 30.0
_ASSET_ROUTE = "/assets/"
_ASSETS_DIR = Path(__file__).with_name("assets")
_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
}


def _read_asset(route: str) -> tuple[bytes, str] | None:
    """Read a bundled client asset, resolving strictly inside the asset root (R3)."""
    if route == "/":
        name = "index.html"
    elif route.startswith(_ASSET_ROUTE):
        name = unquote(route[len(_ASSET_ROUTE) :])
    else:
        return None
    if not name:
        return None
    root = _ASSETS_DIR.resolve()
    try:
        candidate = (root / name).resolve()
    except (OSError, ValueError):
        return None
    if candidate != root and root not in candidate.parents:
        return None
    if not candidate.is_file():
        return None
    content_type = _CONTENT_TYPES.get(candidate.suffix, "application/octet-stream")
    try:
        return candidate.read_bytes(), content_type
    except OSError:
        return None


class _MessageRequest(BaseModel):
    """One ``POST /messages`` body, validated at the transport boundary."""

    model_config = ConfigDict(extra="forbid")

    conversation: str = Field(
        default="default", min_length=1, max_length=_MAX_CONVERSATION_CHARS
    )
    text: str = Field(min_length=1)
    protocol: int = WORKBENCH_PROTOCOL
    capabilities: list[str] = Field(default_factory=list)


class _StreamRequest(BaseModel):
    """One inbound WebSocket text message, validated at the transport boundary."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    protocol: int = WORKBENCH_PROTOCOL


class _Handler(http.server.BaseHTTPRequestHandler):
    """Thin HTTP shim; every decision belongs to the workbench."""

    protocol_version = "HTTP/1.1"
    server: _HttpServer

    def do_GET(self) -> None:
        headers = {name.lower(): value for name, value in self.headers.items()}
        if self.path.split("?", 1)[0] == _STREAM_PATH:
            self.close_connection = True
            outcome = self.server.workbench.stream(
                headers, self.rfile, self.wfile, self.connection, self.path
            )
            if outcome is not None:
                status, payload = outcome
                self._respond(status, payload)
            return
        status, body, content_type = self.server.workbench.get(self.path)
        self._send(status, body, content_type)

    def do_POST(self) -> None:
        length = self.headers.get("Content-Length")
        try:
            size = int(length) if length is not None else 0
        except ValueError:
            self._respond(400, {"error": "invalid Content-Length"})
            return
        if size < 0:
            self._respond(400, {"error": "invalid Content-Length"})
            return
        if size > MAX_MESSAGE_BYTES:
            # Drain a bounded prefix so a cooperating client receives the
            # rejection without buffering the whole advertised body.
            self.rfile.read(MAX_MESSAGE_BYTES + 1)
            self.close_connection = True
            self._respond(413, {"error": "request body too large"})
            return
        body = self.rfile.read(size)
        authorization = self.headers.get("Authorization")
        if self.path.split("?", 1)[0] == _TICKET_PATH:
            status, payload = self.server.workbench.ticket(authorization)
        else:
            status, payload = self.server.workbench.messages(authorization, body)
        self._respond(status, payload)

    def _respond(self, status: int, payload: dict[str, object]) -> None:
        self._send(status, json.dumps(payload).encode("utf-8"), "application/json")

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        """Silence the default stderr access log."""


class _HttpServer(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], workbench: WorkbenchServer) -> None:
        super().__init__(address, _Handler)
        self.workbench = workbench


class WorkbenchServer:
    """Owns the loopback workbench and correlates turns with their replies.

    Binding to ``127.0.0.1`` is deliberate: the host must not expose itself on a
    public interface before an access-control design exists (S5).

    Turns for one conversation run one at a time so each HTTP request can be
    matched to its own reply; different conversations still run concurrently.
    """

    transport_id = WORKBENCH_TRANSPORT_ID

    def __init__(
        self, *, port: int, access: AccessPolicy, submit: InboundHandler
    ) -> None:
        self._requested_port = port
        self._access = access
        self._submit = submit
        self._pending: dict[str, asyncio.Future[str]] = {}
        self._turns: dict[str, asyncio.Lock] = {}
        self._streams: dict[str, queue.Queue[str]] = {}
        self._tickets: dict[str, float] = {}
        self._tickets_lock = threading.Lock()
        self._stopped = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: _HttpServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        """The bound port; only valid once the server has started."""
        if self._server is None:
            raise TransportError("workbench has not started")
        return int(self._server.server_address[1])

    @property
    def url(self) -> str:
        """The base URL clients should use while the server is running."""
        return f"http://{_LOOPBACK}:{self.port}"

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        """Bind the loopback socket and serve it from a background thread."""
        self._stopped.clear()
        try:
            server = _HttpServer((_LOOPBACK, self._requested_port), self)
        except OSError as exc:
            raise TransportError(f"cannot start workbench: {exc}") from exc
        thread = threading.Thread(
            target=server.serve_forever, name="newbot-workbench", daemon=True
        )
        thread.start()
        self._server = server
        self._thread = thread
        self._loop = loop

    def stop(self) -> None:
        """Stop serving and release the socket."""
        self._stopped.set()
        server, thread = self._server, self._thread
        if server is None or thread is None:
            return
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        self._server = None
        self._thread = None
        self._loop = None

    def get(self, path: str) -> tuple[int, bytes, str]:
        """Answer a read-only request; no authentication is required (S5)."""
        route = urlsplit(path).path
        if route == "/health":
            return self._json(200, {"status": "ok"})
        if route == "/capabilities":
            return self._json(
                200,
                {"protocol": WORKBENCH_PROTOCOL, "capabilities": list(CAPABILITIES)},
            )
        asset = _read_asset(route)
        if asset is not None:
            body, content_type = asset
            return 200, body, content_type
        return self._json(404, {"error": "not found"})

    @staticmethod
    def _json(status: int, payload: dict[str, object]) -> tuple[int, bytes, str]:
        return status, json.dumps(payload).encode("utf-8"), "application/json"

    def ticket(self, authorization: str | None) -> tuple[int, dict[str, object]]:
        """Issue a short-lived, single-use ticket for a browser WebSocket upgrade."""
        if not self._access.mutating_enabled:
            return 403, {"error": "mutations are disabled"}
        if not self._access.allows(authorization):
            return 401, {"error": "unauthorized"}
        issued = secrets.token_urlsafe(32)
        now = time.monotonic()
        with self._tickets_lock:
            self._tickets = {
                key: expiry for key, expiry in self._tickets.items() if expiry > now
            }
            self._tickets[issued] = now + _TICKET_TTL_SECONDS
        return 200, {
            "ticket": issued,
            "expiresInSeconds": int(_TICKET_TTL_SECONDS),
        }

    def _consume_ticket(self, protocol: str) -> bool:
        """Validate and consume one ticket offered as a WebSocket subprotocol."""
        value = protocol[len(_TICKET_PROTOCOL_PREFIX) :]
        now = time.monotonic()
        with self._tickets_lock:
            expiry = self._tickets.pop(value, None)
        return expiry is not None and expiry > now

    def messages(
        self, authorization: str | None, body: bytes
    ) -> tuple[int, dict[str, object]]:
        """Authenticate, validate, and run one turn; return its reply."""
        if not self._access.mutating_enabled:
            return 403, {"error": "mutations are disabled"}
        if not self._access.allows(authorization):
            return 401, {"error": "unauthorized"}
        try:
            request = _MessageRequest.model_validate_json(body)
        except ValidationError:
            return 400, {"error": "invalid message request"}
        if request.protocol != WORKBENCH_PROTOCOL:
            return 400, {"error": f"unsupported protocol {request.protocol}"}
        loop = self._loop
        if loop is None:
            raise TransportError("workbench has not started")
        try:
            reply = asyncio.run_coroutine_threadsafe(
                self._run(request.conversation, request.text), loop
            ).result(timeout=_REPLY_TIMEOUT + 5)
        except TimeoutError:
            return 504, {"error": "turn timed out"}
        except TransportError as exc:
            return 502, {"error": str(exc)}
        return 200, {"reply": reply}

    async def deliver(self, envelope: OutboundEnvelope) -> None:
        """Resolve the pending request with the turn's reply."""
        self._resolve(envelope.conversation_id, envelope.text)

    async def publish(self, event: AgentEvent) -> None:
        """Resolve the pending request and forward the event to any stream."""
        if event.session.transport != self.transport_id:
            return
        conversation = event.session.conversation
        if isinstance(event, TurnStarted):
            self._push(conversation, {"type": "started"})
        elif isinstance(event, ResponseDelta):
            self._push(conversation, {"type": "delta", "text": event.text})
        elif isinstance(event, TurnFailed):
            self._push(conversation, {"type": "error", "message": event.message})
            self._fail(conversation, TransportError(event.message))
        elif isinstance(event, TurnCompleted):
            self._push(conversation, {"type": "done", "status": event.status.value})
            self._resolve(conversation, "")

    def stream(
        self,
        headers: Mapping[str, str],
        reader: io.BufferedIOBase,
        writer: io.BufferedIOBase,
        sock: socket.socket,
        path: str,
    ) -> tuple[int, dict[str, object]] | None:
        """Serve one streaming connection; ``None`` means the upgrade happened.

        A non-``None`` result is an HTTP ``(status, payload)`` pair for the
        handler to write because the upgrade was refused.
        """
        refusal = self._upgrade_refusal(headers)
        if refusal is not None:
            return refusal
        conversation = _conversation_from(path)
        if conversation is None:
            return 400, {"error": "invalid conversation"}
        protocol = _ticket_protocol(headers.get("sec-websocket-protocol"))
        handshake = [
            "HTTP/1.1 101 Switching Protocols",
            "Upgrade: websocket",
            "Connection: Upgrade",
            f"Sec-WebSocket-Accept: {accept_key(headers['sec-websocket-key'])}",
        ]
        if protocol is not None:
            handshake.append(f"Sec-WebSocket-Protocol: {protocol}")
        writer.write(("\r\n".join(handshake) + "\r\n\r\n").encode("ascii"))
        writer.flush()
        connection = WebSocketConnection(reader, writer)
        pending: queue.Queue[str] = queue.Queue()
        self._streams[conversation] = pending
        try:
            self._pump(connection, conversation, pending, sock)
        except WebSocketError as exc:
            with contextlib.suppress(OSError):
                connection.close(exc.code, exc.reason)
        except OSError:
            pass
        finally:
            if self._streams.get(conversation) is pending:
                del self._streams[conversation]
        return None

    def _upgrade_refusal(
        self, headers: Mapping[str, str]
    ) -> tuple[int, dict[str, object]] | None:
        if not self._access.mutating_enabled:
            return 403, {"error": "mutations are disabled"}
        ticket = _ticket_protocol(headers.get("sec-websocket-protocol"))
        if ticket is not None:
            if not self._consume_ticket(ticket):
                return 401, {"error": "unauthorized"}
        elif not self._access.allows(headers.get("authorization")):
            return 401, {"error": "unauthorized"}
        if headers.get("upgrade", "").lower() != "websocket":
            return 400, {"error": "expected a websocket upgrade"}
        if "upgrade" not in headers.get("connection", "").lower():
            return 400, {"error": "expected a websocket upgrade"}
        if headers.get("sec-websocket-version") != "13":
            return 400, {"error": "unsupported websocket version"}
        if not headers.get("sec-websocket-key"):
            return 400, {"error": "missing websocket key"}
        return None

    def _pump(
        self,
        connection: WebSocketConnection,
        conversation: str,
        pending: queue.Queue[str],
        sock: socket.socket,
    ) -> None:
        while not self._stopped.is_set():
            readable, _, _ = select.select([sock], [], [], _STREAM_POLL_SECONDS)
            if readable:
                message = connection.receive_text()
                if message is None:
                    return
                self._accept(connection, conversation, message)
            self._flush(connection, pending)

    def _flush(self, connection: WebSocketConnection, pending: queue.Queue[str]) -> None:
        while True:
            try:
                frame = pending.get_nowait()
            except queue.Empty:
                return
            connection.send_text(frame)

    def _accept(
        self, connection: WebSocketConnection, conversation: str, message: str
    ) -> None:
        try:
            request = _StreamRequest.model_validate_json(message)
        except ValidationError:
            connection.send_text(_error_frame("invalid message request"))
            return
        if request.protocol != WORKBENCH_PROTOCOL:
            connection.send_text(_error_frame(f"unsupported protocol {request.protocol}"))
            return
        loop = self._loop
        if loop is None:
            connection.send_text(_error_frame("stream is not running"))
            return
        asyncio.run_coroutine_threadsafe(
            self._submit(
                InboundEnvelope(
                    transport=self.transport_id,
                    conversation_id=conversation,
                    text=request.text,
                )
            ),
            loop,
        )

    def _push(self, conversation: str, frame: dict[str, object]) -> None:
        pending = self._streams.get(conversation)
        if pending is not None:
            pending.put(json.dumps(frame))

    async def _run(self, conversation: str, text: str) -> str:
        # The engine already runs one turn per session; this lock is what
        # makes a reply correlatable: with at most one outstanding future per
        # conversation a delivery can only belong to the turn that registered
        # it, so a queued request waits its turn instead of overwriting the
        # in-flight request's future.
        lock = self._turns.get(conversation)
        if lock is None:
            lock = asyncio.Lock()
            self._turns[conversation] = lock
        async with lock:
            future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
            self._pending[conversation] = future
            try:
                await self._submit(
                    InboundEnvelope(
                        transport=self.transport_id,
                        conversation_id=conversation,
                        text=text,
                    )
                )
                return await asyncio.wait_for(future, timeout=_REPLY_TIMEOUT)
            finally:
                self._pending.pop(conversation, None)

    def _resolve(self, conversation: str, text: str) -> None:
        future = self._pending.get(conversation)
        if future is not None and not future.done():
            future.set_result(text)

    def _fail(self, conversation: str, error: TransportError) -> None:
        future = self._pending.get(conversation)
        if future is not None and not future.done():
            future.set_exception(error)


def _error_frame(message: str) -> str:
    return json.dumps({"type": "error", "message": message})


def _ticket_protocol(header: str | None) -> str | None:
    """Return the offered ticket subprotocol, if the client supplied one."""
    if not header:
        return None
    for candidate in header.split(","):
        token = candidate.strip()
        if token.startswith(_TICKET_PROTOCOL_PREFIX) and len(token) > len(
            _TICKET_PROTOCOL_PREFIX
        ):
            return token
    return None


def _conversation_from(path: str) -> str | None:
    values = parse_qs(urlsplit(path).query).get("conversation", ["default"])
    conversation = values[0]
    if not conversation or len(conversation) > _MAX_CONVERSATION_CHARS:
        return None
    return conversation
