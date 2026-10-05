"""Process-level CLI smoke tests against a local stub completion server."""

from __future__ import annotations

import http.server
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"

_TEXT_SSE = (
    b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
    b'data: {"choices":[{"delta":{"content":", world"}}]}\n\n'
    b"data: [DONE]\n\n"
)

_TOOL_CALL_SSE = (
    b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1",'
    b'"function":{"name":"read_file","arguments":"{\\"path\\":\\"note.txt\\"}"}}]}}]}\n\n'
    b"data: [DONE]\n\n"
)

_FINAL_SSE = (
    b'data: {"choices":[{"delta":{"content":"The note says payload-42"}}]}\n\n'
    b"data: [DONE]\n\n"
)

_SHELL_CALL_SSE = (
    b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1",'
    b'"function":{"name":"run_shell","arguments":'
    b'"{\\"command\\":\\"echo agent-shell-ok\\"}"}}]}}]}\n\n'
    b"data: [DONE]\n\n"
)

_SHELL_OK_SSE = (
    b'data: {"choices":[{"delta":{"content":"shell said agent-shell-ok"}}]}\n\n'
    b"data: [DONE]\n\n"
)

_SHELL_BAD_SSE = (
    b'data: {"choices":[{"delta":{"content":"shell tool failed"}}]}\n\n'
    b"data: [DONE]\n\n"
)


class _StubBase(http.server.BaseHTTPRequestHandler):
    def _respond(self, body: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


class _TextStub(_StubBase):
    def do_POST(self) -> None:
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self._respond(_TEXT_SSE)


class _ToolStub(_StubBase):
    def do_POST(self) -> None:
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        payload = json.loads(raw)
        used_tool = any(item.get("role") == "tool" for item in payload["messages"])
        self._respond(_FINAL_SSE if used_tool else _TOOL_CALL_SSE)


class _ShellStub(_StubBase):
    def do_POST(self) -> None:
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        payload = json.loads(raw)
        tool_messages = [
            item for item in payload["messages"] if item.get("role") == "tool"
        ]
        if not tool_messages:
            self._respond(_SHELL_CALL_SSE)
            return
        output = "".join(item.get("content", "") for item in tool_messages)
        self._respond(_SHELL_OK_SSE if "agent-shell-ok" in output else _SHELL_BAD_SSE)


def _smoke(
    handler: type[http.server.BaseHTTPRequestHandler],
    tmp_path: Path,
    *,
    workspace: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        lines = [
            "[provider]",
            f'baseUrl = "http://127.0.0.1:{port}/v1"',
            'apiKey = "test-key"',
            "",
            "[agent]",
            'model = "stub"',
        ]
        if workspace is not None:
            lines.append(f'workspace = "{workspace.as_posix()}"')
        lines.extend(
            [
                "",
                "[sessions]",
                f'dir = "{(tmp_path / "sessions").as_posix()}"',
            ]
        )
        config = tmp_path / "config.toml"
        config.write_text("\n".join(lines) + "\n", encoding="utf-8")
        env = dict(os.environ)
        env["PYTHONPATH"] = str(SRC)
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "newbot",
                "run",
                "-m",
                "hello",
                "--config",
                str(config),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=30,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_cli_streams_reply_from_local_provider(tmp_path: Path) -> None:
    result = _smoke(_TextStub, tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "Hello, world\n"


def test_cli_executes_a_tool_against_the_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "note.txt").write_text("payload-42", encoding="utf-8")

    result = _smoke(_ToolStub, tmp_path, workspace=workspace)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "The note says payload-42\n"


def test_cli_runs_a_shell_tool_end_to_end(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()

    result = _smoke(_ShellStub, tmp_path, workspace=workspace)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "shell said agent-shell-ok\n"
