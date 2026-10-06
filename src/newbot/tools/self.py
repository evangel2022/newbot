"""Read-only self-inspection tool (``my``)."""

from __future__ import annotations

import json
from collections.abc import Mapping

from newbot.domain.errors import ToolError
from newbot.domain.tool import ToolSpec
from newbot.ports.tools import ToolContext
from newbot.tools.base import ToolOutput

_SCHEMA: Mapping[str, object] = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["check"],
            "description": "Only 'check' is supported; the tool is read-only.",
        },
        "key": {
            "type": "string",
            "description": "Optional top-level key to return instead of the overview.",
        },
    },
    "required": ["action"],
    "additionalProperties": False,
}


class MyTool:
    """Reports this runtime's own configuration; read-only.

    The snapshot is assembled by the composition root, so the tool never reads
    process-global state and never exposes secrets: only the non-secret facts
    listed there, plus the per-turn workspace and session from the tool context.
    """

    def __init__(self, state: Mapping[str, object]) -> None:
        self._state = dict(state)
        self.spec = ToolSpec(
            name="my",
            description=(
                "Inspect this runtime's own configuration (model, provider, "
                "workspace, session, limits). Read-only."
            ),
            parameters=_SCHEMA,
        )

    async def invoke(
        self, arguments: Mapping[str, object], ctx: ToolContext
    ) -> ToolOutput:
        if arguments.get("action") != "check":
            raise ToolError("argument 'action' must be 'check' (read-only)")
        state: dict[str, object] = {
            **self._state,
            "workspace": str(ctx.workspace_root),
            "session": {
                "transport": ctx.session.transport,
                "conversation": ctx.session.conversation,
            },
        }
        key = arguments.get("key")
        if key is None:
            return ToolOutput(text=_overview(state))
        if not isinstance(key, str) or key not in state:
            raise ToolError(f"unknown key {key!r}")
        return ToolOutput(text=f"{key}: {_render(state[key])}")


def _overview(state: Mapping[str, object]) -> str:
    return "\n".join(f"{key}: {_render(state[key])}" for key in sorted(state))


def _render(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)
