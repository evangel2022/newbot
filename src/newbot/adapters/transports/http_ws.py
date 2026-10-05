"""Loopback HTTP surface for the long-running host (health today, workbench later)."""

from __future__ import annotations

import http.server
import json
import threading

from newbot.domain.errors import TransportError

_LOOPBACK = "127.0.0.1"
_HEALTH_PATH = "/health"
_HEALTH_BODY = json.dumps({"status": "ok"}).encode("utf-8")


class _HealthHandler(http.server.BaseHTTPRequestHandler):
    """Serves ``GET /health`` and rejects every other path."""

    def do_GET(self) -> None:
        if self.path != _HEALTH_PATH:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(_HEALTH_BODY)))
        self.end_headers()
        self.wfile.write(_HEALTH_BODY)

    def log_message(self, format: str, *args: object) -> None:
        """Silence the default stderr access log."""


class _HealthServer(http.server.ThreadingHTTPServer):
    daemon_threads = True


class HealthServer:
    """Owns a loopback-only HTTP server that reports host health.

    Binding to ``127.0.0.1`` is deliberate: the host must not expose itself on a
    public interface before an access-control design exists (S5).
    """

    def __init__(self, *, port: int) -> None:
        self._requested_port = port
        self._server: _HealthServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        """The bound port; only valid once the server has started."""
        if self._server is None:
            raise TransportError("health server has not started")
        return int(self._server.server_address[1])

    @property
    def url(self) -> str:
        """The base URL clients should use while the server is running."""
        return f"http://{_LOOPBACK}:{self.port}"

    def start(self) -> None:
        """Bind the loopback socket and serve it from a background thread."""
        try:
            server = _HealthServer((_LOOPBACK, self._requested_port), _HealthHandler)
        except OSError as exc:
            raise TransportError(f"cannot start health server: {exc}") from exc
        thread = threading.Thread(
            target=server.serve_forever, name="newbot-health", daemon=True
        )
        thread.start()
        self._server = server
        self._thread = thread

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
