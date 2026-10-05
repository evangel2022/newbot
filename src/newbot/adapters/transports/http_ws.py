"""Loopback HTTP workbench: health, capability negotiation, and turn submission."""

from __future__ import annotations

import asyncio
import http.server
import json
import threading

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from newbot.domain.envelope import InboundEnvelope, OutboundEnvelope
from newbot.domain.errors import TransportError
from newbot.domain.events import AgentEvent, TurnCompleted, TurnFailed
from newbot.policy.access import AccessPolicy
from newbot.ports.transports import InboundHandler

WORKBENCH_PROTOCOL = 1
WORKBENCH_TRANSPORT_ID = "webui"
CAPABILITIES: tuple[str, ...] = ("chat",)

_LOOPBACK = "127.0.0.1"
_REPLY_TIMEOUT = 120.0


class _MessageRequest(BaseModel):
    """One ``POST /messages`` body, validated at the transport boundary."""

    model_config = ConfigDict(extra="forbid")

    conversation: str = Field(default="default", min_length=1)
    text: str = Field(min_length=1)
    protocol: int = WORKBENCH_PROTOCOL
    capabilities: list[str] = Field(default_factory=list)


class _Handler(http.server.BaseHTTPRequestHandler):
    """Thin HTTP shim; every decision belongs to the workbench."""

    server: _HttpServer

    def do_GET(self) -> None:
        status, payload = self.server.workbench.get(self.path)
        self._respond(status, payload)

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
        body = self.rfile.read(size)
        status, payload = self.server.workbench.messages(
            self.headers.get("Authorization"), body
        )
        self._respond(status, payload)

    def _respond(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
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
    """

    transport_id = WORKBENCH_TRANSPORT_ID

    def __init__(
        self, *, port: int, access: AccessPolicy, submit: InboundHandler
    ) -> None:
        self._requested_port = port
        self._access = access
        self._submit = submit
        self._pending: dict[str, asyncio.Future[str]] = {}
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
        server, thread = self._server, self._thread
        if server is None or thread is None:
            return
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        self._server = None
        self._thread = None
        self._loop = None

    def get(self, path: str) -> tuple[int, dict[str, object]]:
        """Answer a read-only request; no authentication is required (S5)."""
        if path == "/health":
            return 200, {"status": "ok"}
        if path == "/capabilities":
            return 200, {
                "protocol": WORKBENCH_PROTOCOL,
                "capabilities": list(CAPABILITIES),
            }
        return 404, {"error": "not found"}

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
        """Resolve or fail the pending request at the turn boundary."""
        if event.session.transport != self.transport_id:
            return
        if isinstance(event, TurnFailed):
            self._fail(event.session.conversation, TransportError(event.message))
        elif isinstance(event, TurnCompleted):
            self._resolve(event.session.conversation, "")

    async def _run(self, conversation: str, text: str) -> str:
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
