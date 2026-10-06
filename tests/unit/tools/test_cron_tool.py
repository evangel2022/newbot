"""Contract tests for the cron tool against an in-memory job store."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from newbot.domain.errors import ToolError
from newbot.domain.session import SessionKey
from newbot.ports.tools import ToolContext
from newbot.tools.cron import CronTool
from support import MemoryJobStore

CTX = ToolContext(
    session=SessionKey(transport="webui", conversation="ops"),
    workspace_root=Path("."),
)


def _clock() -> datetime:
    return datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def _tool() -> tuple[CronTool, MemoryJobStore]:
    store = MemoryJobStore()
    return CronTool(store, clock=_clock), store


async def test_add_schedules_a_recurring_job_in_the_calling_session() -> None:
    tool, store = _tool()

    output = await tool.invoke(
        {"action": "add", "prompt": "check the build", "every_seconds": 60}, CTX
    )

    assert "every 60s" in output.text
    assert "host is serving" in output.text
    job = store.jobs()[0]
    assert job.transport == "webui"
    assert job.conversation == "ops"
    assert job.prompt == "check the build"
    assert job.every_seconds == 60
    assert job.next_run_at == datetime(2026, 10, 5, 12, 1, tzinfo=UTC)


async def test_add_schedules_a_one_shot_job() -> None:
    tool, store = _tool()

    output = await tool.invoke(
        {"action": "add", "prompt": "ping", "delay_seconds": 30}, CTX
    )

    assert "once" in output.text
    job = store.jobs()[0]
    assert job.every_seconds is None
    assert job.next_run_at == datetime(2026, 10, 5, 12, 0, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"action": "pause"},
        {"action": "add", "prompt": "x"},
        {"action": "add", "prompt": "x", "every_seconds": 60, "delay_seconds": 60},
        {"action": "add", "prompt": "x", "every_seconds": 0},
        {"action": "add", "prompt": "x", "every_seconds": -1},
        {"action": "add", "prompt": "x", "every_seconds": True},
        {"action": "add", "prompt": "x", "every_seconds": "60"},
        {"action": "add", "every_seconds": 60},
        {"action": "remove"},
    ],
    ids=[
        "no-action",
        "unknown-action",
        "no-cadence",
        "both-cadences",
        "zero-interval",
        "negative-interval",
        "boolean-interval",
        "string-interval",
        "no-prompt",
        "no-job-id",
    ],
)
async def test_invalid_arguments_are_tool_errors(
    arguments: dict[str, object],
) -> None:
    tool, store = _tool()

    with pytest.raises(ToolError):
        await tool.invoke(arguments, CTX)

    assert store.jobs() == ()


async def test_list_reports_every_job() -> None:
    tool, _store = _tool()
    await tool.invoke({"action": "add", "prompt": "check", "every_seconds": 60}, CTX)
    await tool.invoke({"action": "add", "prompt": "once", "delay_seconds": 30}, CTX)

    output = await tool.invoke({"action": "list"}, CTX)

    assert "job-1" in output.text
    assert "every 60s" in output.text
    assert "job-2" in output.text
    assert "'once'" in output.text


async def test_list_is_empty_when_nothing_is_scheduled() -> None:
    tool, _store = _tool()

    assert (await tool.invoke({"action": "list"}, CTX)).text == "no scheduled jobs"


async def test_remove_drops_a_job_and_reports_an_unknown_id() -> None:
    tool, store = _tool()
    await tool.invoke({"action": "add", "prompt": "check", "every_seconds": 60}, CTX)

    removed = await tool.invoke({"action": "remove", "job_id": "job-1"}, CTX)
    missing = await tool.invoke({"action": "remove", "job_id": "job-9"}, CTX)

    assert removed.text == "removed job-1"
    assert "no job" in missing.text
    assert store.jobs() == ()
