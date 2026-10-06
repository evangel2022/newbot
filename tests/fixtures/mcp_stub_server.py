"""A minimal stdio MCP server used by newbot tests.

Speaks newline-delimited JSON-RPC over stdin/stdout and advertises one ``echo``
tool. Invoked with ``--error`` it answers every request with a JSON-RPC error,
so the client's protocol-failure path can be exercised.
"""

from __future__ import annotations

import json
import sys


def _echo_tool() -> dict[str, object]:
    return {
        "name": "echo",
        "description": "Echo the given text back.",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
    }


def _handle(
    message: dict[str, object], *, fail: bool
) -> dict[str, object] | None:
    request_id = message.get("id")
    if request_id is None:
        return None
    if fail:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32000, "message": "stub refused"},
        }
    method = message.get("method")
    if method == "initialize":
        result: object = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "stub", "version": "1"},
        }
    elif method == "tools/list":
        result = {"tools": [_echo_tool()]}
    elif method == "tools/call":
        params = message.get("params")
        arguments = params.get("arguments", {}) if isinstance(params, dict) else {}
        text = arguments.get("text", "") if isinstance(arguments, dict) else ""
        result = {
            "content": [{"type": "text", "text": f"echo: {text}"}],
            "isError": text == "boom",
        }
    else:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"unknown method {method}"},
        }
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def main(argv: list[str]) -> int:
    fail = "--error" in argv
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        response = _handle(json.loads(line), fail=fail)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
