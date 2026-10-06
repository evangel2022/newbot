"""Contract tests for the delegate tool's actions."""

from __future__ import annotations

from pathlib import Path

import pytest

from newbot.domain.errors import ToolError
from newbot.domain.session import SessionKey
from newbot.domain.subagent import SubagentStatus, SubagentTask
from newbot.ports.tools import ToolContext
from newbot.tools.delegate import DelegateTool

CTX = ToolContext(session=SessionKey("cli", "default"), workspace_root=Path("."))


def _task(status: SubagentStatus, text: str = "", task_id: str = "task-1") -> SubagentTask:
    return SubagentTask(id=task_id, status=status, text=text)


class _StubSubagents:
    def __init__(
        self, *, run: SubagentTask | None = None, wait: SubagentTask | None = None
    ) -> None:
        self._run = run or _task(SubagentStatus.COMPLETED, "child says hi")
        self._wait = wait
        self.calls: list[tuple[str, str, SessionKey]] = []

    async def run(self, task, *, parent, workspace_root):
        self.calls.append(("run", task, parent))
        return self._run

    async def start(self, task, *, parent, workspace_root):
        self.calls.append(("start", task, parent))
        return _task(SubagentStatus.RUNNING)

    async def status(self, task_id, *, parent):
        self.calls.append(("status", task_id, parent))
        return _task(SubagentStatus.RUNNING, task_id=task_id)

    async def wait(self, task_id, *, parent):
        self.calls.append(("wait", task_id, parent))
        return self._wait or _task(
            SubagentStatus.COMPLETED, "waited", task_id=task_id
        )

    async def cancel(self, task_id, *, parent):
        self.calls.append(("cancel", task_id, parent))
        return _task(SubagentStatus.CANCELLED, task_id=task_id)


async def test_run_returns_the_child_reply() -> None:
    subagents = _StubSubagents()

    result = await DelegateTool(subagents).invoke({"task": "do it"}, CTX)

    assert result.is_error is False
    assert result.text == "child says hi"
    assert subagents.calls == [("run", "do it", CTX.session)]


async def test_start_returns_a_running_task_id() -> None:
    result = await DelegateTool(_StubSubagents()).invoke(
        {"action": "start", "task": "long"}, CTX
    )

    assert result.text == "started task-1"


async def test_status_reports_a_running_task() -> None:
    result = await DelegateTool(_StubSubagents()).invoke(
        {"action": "status", "task_id": "task-1"}, CTX
    )

    assert result.text == "task-1 is running"


async def test_wait_returns_the_finished_text() -> None:
    result = await DelegateTool(_StubSubagents()).invoke(
        {"action": "wait", "task_id": "task-1"}, CTX
    )

    assert result.text == "waited"


async def test_cancel_reports_the_cancellation() -> None:
    result = await DelegateTool(_StubSubagents()).invoke(
        {"action": "cancel", "task_id": "task-1"}, CTX
    )

    assert result.text == "task-1 was cancelled"


async def test_wait_renders_an_interrupted_task() -> None:
    subagents = _StubSubagents(wait=_task(SubagentStatus.INTERRUPTED, "half"))

    result = await DelegateTool(subagents).invoke(
        {"action": "wait", "task_id": "task-1"}, CTX
    )

    assert "interrupted" in result.text
    assert "half" in result.text


async def test_run_marks_an_incomplete_child() -> None:
    subagents = _StubSubagents(run=_task(SubagentStatus.INCOMPLETE, "partial"))

    result = await DelegateTool(subagents).invoke({"task": "loop"}, CTX)

    assert "partial" in result.text
    assert "iteration limit" in result.text


async def test_run_reports_a_failed_child() -> None:
    subagents = _StubSubagents(run=_task(SubagentStatus.FAILED, "boom"))

    with pytest.raises(ToolError, match="subagent task-1 failed: boom"):
        await DelegateTool(subagents).invoke({"task": "x"}, CTX)


async def test_unknown_action_is_rejected() -> None:
    with pytest.raises(ToolError, match="action"):
        await DelegateTool(_StubSubagents()).invoke({"action": "nope"}, CTX)


async def test_run_requires_a_task() -> None:
    with pytest.raises(ToolError):
        await DelegateTool(_StubSubagents()).invoke({}, CTX)


async def test_control_actions_require_a_task_id() -> None:
    with pytest.raises(ToolError):
        await DelegateTool(_StubSubagents()).invoke({"action": "wait"}, CTX)
