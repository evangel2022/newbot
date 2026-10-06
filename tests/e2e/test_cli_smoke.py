"""Process-level CLI smoke tests against a local stub completion server."""

from __future__ import annotations

import http.server
import io
import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
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

_MCP_CALL_SSE = (
    b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1",'
    b'"function":{"name":"mcp__stub__echo",'
    b'"arguments":"{\\"text\\":\\"hello-mcp\\"}"}}]}}]}\n\n'
    b"data: [DONE]\n\n"
)

_SKILL_CALL_SSE = (
    b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1",'
    b'"function":{"name":"skill",'
    b'"arguments":"{\\"action\\":\\"read\\",\\"name\\":\\"greet\\"}"}}]}}]}\n\n'
    b"data: [DONE]\n\n"
)

_EDIT_CALL_SSE = (
    b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1",'
    b'"function":{"name":"edit_file","arguments":'
    b'"{\\"path\\":\\"note.txt\\",\\"old_string\\":\\"before\\",'
    b'\\"new_string\\":\\"after\\"}"}}]}}]}\n\n'
    b"data: [DONE]\n\n"
)

_EDIT_OK_SSE = (
    b'data: {"choices":[{"delta":{"content":"edited the note"}}]}\n\n'
    b"data: [DONE]\n\n"
)

_NOTE_PATCH = (
    "--- a/note.txt\n"
    "+++ b/note.txt\n"
    "@@ -1,3 +1,3 @@\n"
    " one\n"
    "-two\n"
    "+TWO\n"
    " three\n"
)

_PATCH_CALL_SSE = (
    "data: "
    + json.dumps(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {
                                    "name": "apply_patch",
                                    "arguments": json.dumps({"patch": _NOTE_PATCH}),
                                },
                            }
                        ]
                    }
                }
            ]
        }
    )
    + "\n\ndata: [DONE]\n\n"
).encode()

_PATCH_OK_SSE = (
    b'data: {"choices":[{"delta":{"content":"patched the note"}}]}\n\n'
    b"data: [DONE]\n\n"
)

_MY_CALL_SSE = (
    b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1",'
    b'"function":{"name":"my","arguments":"{\\"action\\":\\"check\\"}"}}]}}]}\n\n'
    b"data: [DONE]\n\n"
)

_MY_OK_SSE = (
    b'data: {"choices":[{"delta":{"content":"model is stub"}}]}\n\n'
    b"data: [DONE]\n\n"
)

_MY_BAD_SSE = (
    b'data: {"choices":[{"delta":{"content":"missing config"}}]}\n\n'
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


class _McpStub(_StubBase):
    def do_POST(self) -> None:
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        payload = json.loads(raw)
        tool_messages = [
            item for item in payload["messages"] if item.get("role") == "tool"
        ]
        if not tool_messages:
            self._respond(_MCP_CALL_SSE)
            return
        output = "".join(item.get("content", "") for item in tool_messages)
        content = json.dumps(f"mcp said {output}")
        body = (
            f'data: {{"choices":[{{"delta":{{"content":{content}}}}}]}}\n\n'
            "data: [DONE]\n\n"
        ).encode()
        self._respond(body)


class _SkillStub(_StubBase):
    def do_POST(self) -> None:
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        payload = json.loads(raw)
        tool_messages = [
            item for item in payload["messages"] if item.get("role") == "tool"
        ]
        if not tool_messages:
            self._respond(_SKILL_CALL_SSE)
            return
        output = "".join(item.get("content", "") for item in tool_messages)
        content = json.dumps(f"skill said {output.strip()}")
        body = (
            f'data: {{"choices":[{{"delta":{{"content":{content}}}}}]}}\n\n'
            "data: [DONE]\n\n"
        ).encode()
        self._respond(body)


class _EditStub(_StubBase):
    def do_POST(self) -> None:
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        payload = json.loads(raw)
        used_tool = any(item.get("role") == "tool" for item in payload["messages"])
        self._respond(_EDIT_OK_SSE if used_tool else _EDIT_CALL_SSE)


class _PatchStub(_StubBase):
    def do_POST(self) -> None:
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        payload = json.loads(raw)
        used_tool = any(item.get("role") == "tool" for item in payload["messages"])
        self._respond(_PATCH_OK_SSE if used_tool else _PATCH_CALL_SSE)


class _MyStub(_StubBase):
    def do_POST(self) -> None:
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        payload = json.loads(raw)
        tool_messages = [
            item for item in payload["messages"] if item.get("role") == "tool"
        ]
        if not tool_messages:
            self._respond(_MY_CALL_SSE)
            return
        output = "".join(item.get("content", "") for item in tool_messages)
        self._respond(_MY_OK_SSE if 'model: "stub"' in output else _MY_BAD_SSE)


class _TelegramStubServer(http.server.ThreadingHTTPServer):
    """Tracks a pre-startup backlog, a new message, and the replies sent."""

    def __init__(self, address: tuple[str, int], handler: type) -> None:
        super().__init__(address, handler)
        self.drained = False
        self.delivered = False
        self.sent: list[dict[str, object]] = []


class _TelegramStub(http.server.BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        server = self.server
        assert isinstance(server, _TelegramStubServer)
        if self.path.endswith("/getUpdates"):
            if not server.drained:
                server.drained = True
                self._json({"ok": True, "result": [_telegram_update(1, "old")]})
            elif not server.delivered:
                server.delivered = True
                self._json({"ok": True, "result": [_telegram_update(2, "hi")]})
            else:
                time.sleep(0.02)
                self._json({"ok": True, "result": []})
            return
        if self.path.endswith("/sendMessage"):
            server.sent.append(json.loads(raw))
            self._json({"ok": True, "result": {"message_id": 1}})
            return
        self.send_error(404)

    def _json(self, payload: object) -> None:
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


def _telegram_update(update_id: int, text: str) -> dict[str, object]:
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "chat": {"id": 42, "type": "private"},
            "text": text,
        },
    }


def _smoke(
    handler: type[http.server.BaseHTTPRequestHandler],
    tmp_path: Path,
    *,
    workspace: Path | None = None,
    extra: Sequence[str] = (),
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
                *extra,
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


def test_cli_edits_a_workspace_file(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "note.txt").write_text("before", encoding="utf-8")

    result = _smoke(_EditStub, tmp_path, workspace=workspace)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "edited the note\n"
    assert (workspace / "note.txt").read_text(encoding="utf-8") == "after"


def test_cli_applies_a_patch_to_a_workspace_file(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "note.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")

    result = _smoke(_PatchStub, tmp_path, workspace=workspace)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "patched the note\n"
    assert (workspace / "note.txt").read_text(encoding="utf-8") == "one\nTWO\nthree\n"


def test_cli_reports_its_own_runtime_state(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()

    result = _smoke(_MyStub, tmp_path, workspace=workspace)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "model is stub\n"


def test_cli_runs_a_shell_tool_end_to_end(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()

    result = _smoke(_ShellStub, tmp_path, workspace=workspace)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "shell said agent-shell-ok\n"


def test_cli_calls_a_tool_on_a_configured_mcp_server(tmp_path: Path) -> None:
    script = REPO_ROOT / "tests" / "fixtures" / "mcp_stub_server.py"
    command = sys.executable.replace("\\", "/")

    result = _smoke(
        _McpStub,
        tmp_path,
        extra=[
            "[tools.mcp.servers.stub]",
            f'command = "{command}"',
            f'args = ["{script.as_posix()}"]',
        ],
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "mcp said echo: hello-mcp\n"


def test_cli_calls_a_tool_on_a_plugin_bundled_mcp_server(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    plugin = workspace / "plugins" / "bundle"
    plugin.mkdir(parents=True)
    (plugin / "plugin.json").write_text('{"name": "bundle"}', encoding="utf-8")
    script = REPO_ROOT / "tests" / "fixtures" / "mcp_stub_server.py"
    (plugin / "mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "stub": {
                        "command": sys.executable.replace("\\", "/"),
                        "args": [script.as_posix()],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    result = _smoke(
        _McpStub,
        tmp_path,
        workspace=workspace,
        extra=["", "[plugins]", 'enabled = ["bundle"]'],
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "mcp said echo: hello-mcp\n"


def test_cli_offers_a_workspace_skill_to_the_model(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    directory = workspace / "skills" / "greet"
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        "---\ndescription: Say hello nicely\n---\n\nGreet the user warmly.\n",
        encoding="utf-8",
    )

    result = _smoke(_SkillStub, tmp_path, workspace=workspace)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "skill said Greet the user warmly.\n"


def test_cli_offers_a_plugin_skill_to_the_model(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    plugin = workspace / "plugins" / "greeter"
    directory = plugin / "skills" / "greet"
    directory.mkdir(parents=True)
    (plugin / "plugin.json").write_text('{"name": "greeter"}', encoding="utf-8")
    (directory / "SKILL.md").write_text(
        "---\ndescription: Say hello nicely\n---\n\nGreet the user warmly.\n",
        encoding="utf-8",
    )

    result = _smoke(
        _SkillStub,
        tmp_path,
        workspace=workspace,
        extra=["", "[plugins]", 'enabled = ["greeter"]'],
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "skill said Greet the user warmly.\n"


def test_serve_runs_a_scheduled_turn_in_its_bound_conversation(
    tmp_path: Path,
) -> None:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _TextStub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        process, sessions_dir = _start_serve(
            tmp_path,
            server.server_address[1],
            extra=[
                "[[schedule.turns]]",
                "everySeconds = 0.05",
                'conversation = "ops"',
                'prompt = "say hello"',
            ],
        )
        try:
            _read_until(process.stdout, "health http://")
            _wait_for_text(sessions_dir, "Hello, world")
        finally:
            _stop(process)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_serve_runs_a_heartbeat_task_from_the_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "HEARTBEAT.md").write_text(
        "## Active Tasks\n\n- Watch the build\n", encoding="utf-8"
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _TextStub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        process, sessions_dir = _start_serve(
            tmp_path,
            server.server_address[1],
            workspace=workspace,
            extra=[
                "[heartbeat]",
                "enabled = true",
                "intervalSeconds = 0.05",
                'conversation = "checks"',
            ],
        )
        try:
            _read_until(process.stdout, "health http://")
            _wait_for_text(sessions_dir, "Watch the build")
            _wait_for_text(sessions_dir, "Hello, world")
        finally:
            _stop(process)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_serve_answers_a_telegram_message(tmp_path: Path) -> None:
    telegram = _TelegramStubServer(("127.0.0.1", 0), _TelegramStub)
    telegram_thread = threading.Thread(target=telegram.serve_forever, daemon=True)
    telegram_thread.start()
    provider = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _TextStub)
    provider_thread = threading.Thread(target=provider.serve_forever, daemon=True)
    provider_thread.start()
    try:
        process, _ = _start_serve(
            tmp_path,
            provider.server_address[1],
            extra=[
                "[channels.telegram]",
                "enabled = true",
                'token = "test-token"',
                f'apiBase = "http://127.0.0.1:{telegram.server_address[1]}"',
                "pollTimeoutSeconds = 0.1",
            ],
        )
        try:
            _read_until(process.stdout, "health http://")
            sent = _wait_for_telegram_reply(telegram)
        finally:
            _stop(process)
    finally:
        telegram.shutdown()
        provider.shutdown()
        telegram_thread.join(timeout=5)
        provider_thread.join(timeout=5)

    assert sent == [{"chat_id": 42, "text": "Hello, world"}]


def test_serve_runs_an_agent_created_job_from_its_registry(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    registry = workspace / "cron"
    registry.mkdir(parents=True)
    (registry / "jobs.json").write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "id": "seed",
                        "transport": "webui",
                        "conversation": "ops",
                        "prompt": "cron-marker-7",
                        "next_run_at": "2000-01-01T00:00:00+00:00",
                        "every_seconds": None,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _TextStub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        process, sessions_dir = _start_serve(
            tmp_path,
            server.server_address[1],
            workspace=workspace,
            extra=[],
        )
        try:
            _read_until(process.stdout, "health http://")
            _wait_for_text(sessions_dir, "cron-marker-7")
            _wait_for_text(sessions_dir, "Hello, world")
        finally:
            _stop(process)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _start_serve(
    tmp_path: Path,
    port: int,
    *,
    extra: list[str],
    workspace: Path | None = None,
) -> tuple[subprocess.Popen[str], Path]:
    sessions_dir = tmp_path / "sessions"
    config = tmp_path / "config.toml"
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
            f'dir = "{sessions_dir.as_posix()}"',
            "",
            "[server]",
            "port = 0",
            "",
            *extra,
        ]
    )
    config.write_text("\n".join(lines) + "\n", encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    process = subprocess.Popen(
        [sys.executable, "-m", "newbot", "serve", "--config", str(config)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    assert process.stdout is not None
    return process, sessions_dir


def _stop(process: subprocess.Popen[str]) -> None:
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def _wait_for_telegram_reply(
    server: _TelegramStubServer, *, timeout: float = 30.0
) -> list[dict[str, object]]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server.sent:
            time.sleep(0.5)
            return list(server.sent)
        time.sleep(0.05)
    raise TimeoutError("telegram reply was not sent")


def _read_until(stream: io.TextIOBase, needle: str, *, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while True:
        line = stream.readline()
        if needle in line:
            return
        if not line or time.monotonic() > deadline:
            raise TimeoutError(f"{needle!r} was not printed")


def _wait_for_text(root: Path, needle: str, *, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if needle in text:
                return
        time.sleep(0.05)
    raise TimeoutError(f"{needle!r} was not recorded under {root}")
