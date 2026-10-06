"""The agent-facing tool that runs and controls subagent tasks."""

from __future__ import annotations

from collections.abc import Mapping

from newbot.domain.errors import ToolError
from newbot.domain.subagent import SubagentStatus, SubagentTask
from newbot.domain.tool import ToolSpec
from newbot.ports.subagents import SubagentPort
from newbot.ports.tools import ToolContext
from newbot.tools.base import ToolOutput, require_string

_ACTIONS = ("run", "start", "status", "wait", "cancel")

_SCHEMA: Mapping[str, object] = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": list(_ACTIONS),
            "description": (
                "run (default) starts and waits; start runs in the background; "
                "status, wait, and cancel address a task_id."
            ),
        },
        "task": {
            "type": "string",
            "description": "A self-contained task, required for run and start.",
        },
        "task_id": {
            "type": "string",
            "description": "The task to address, required for status, wait, cancel.",
        },
    },
    "additionalProperties": False,
}


class DelegateTool:
    """Delegates a task to a subagent and controls it."""

    def __init__(self, subagents: SubagentPort) -> None:
        self._subagents = subagents
        self.spec = ToolSpec(
            name="delegate",
            description=(
                "Delegate a self-contained task to a subagent with its own context. "
                "Run and wait for it, or start it in the background and later check, "
                "wait on, or cancel it."
            ),
            parameters=_SCHEMA,
        )

    async def invoke(
        self, arguments: Mapping[str, object], ctx: ToolContext
    ) -> ToolOutput:
        action = arguments.get("action", "run")
        if not isinstance(action, str) or action not in _ACTIONS:
            raise ToolError(
                f"argument 'action' must be one of {', '.join(_ACTIONS)}"
            )
        if action in ("run", "start"):
            return await self._begin(action, arguments, ctx)
        task_id = require_string(arguments, "task_id")
        if action == "status":
            view = await self._subagents.status(task_id, parent=ctx.session)
        elif action == "wait":
            view = await self._subagents.wait(task_id, parent=ctx.session)
        else:
            view = await self._subagents.cancel(task_id, parent=ctx.session)
        return _render(view)

    async def _begin(
        self, action: str, arguments: Mapping[str, object], ctx: ToolContext
    ) -> ToolOutput:
        task = require_string(arguments, "task")
        if action == "start":
            view = await self._subagents.start(
                task, parent=ctx.session, workspace_root=ctx.workspace_root
            )
            return ToolOutput(text=f"started {view.id}")
        view = await self._subagents.run(
            task, parent=ctx.session, workspace_root=ctx.workspace_root
        )
        return _render(view)


def _render(view: SubagentTask) -> ToolOutput:
    if view.status is SubagentStatus.RUNNING:
        return ToolOutput(text=f"{view.id} is running")
    if view.status is SubagentStatus.CANCELLED:
        return ToolOutput(text=f"{view.id} was cancelled")
    if view.status is SubagentStatus.INTERRUPTED:
        if view.text:
            return ToolOutput(
                text=f"{view.id} was interrupted; partial result:\n{view.text}"
            )
        return ToolOutput(text=f"{view.id} was interrupted")
    if view.status is SubagentStatus.FAILED:
        raise ToolError(f"subagent {view.id} failed: {view.text}")
    if view.status is SubagentStatus.INCOMPLETE:
        return ToolOutput(
            text=f"{view.text}\n\n(subagent stopped at its iteration limit)"
        )
    return ToolOutput(text=view.text)
