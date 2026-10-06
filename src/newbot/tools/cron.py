"""Agent-facing scheduler for jobs bound to the calling session."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import timedelta

from newbot.domain.errors import ToolError
from newbot.domain.job import Clock, ScheduledJob, utcnow
from newbot.domain.tool import ToolSpec
from newbot.ports.jobs import JobStorePort
from newbot.ports.tools import ToolContext
from newbot.tools.base import ToolOutput, require_string

_SCHEMA: Mapping[str, object] = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["add", "list", "remove"],
            "description": "Schedule a job, list jobs, or remove a job by id.",
        },
        "prompt": {
            "type": "string",
            "description": "The turn to run when the job fires; add needs it.",
        },
        "every_seconds": {
            "type": "number",
            "description": (
                "Repeat every this many seconds; add needs it unless "
                "delay_seconds is given."
            ),
        },
        "delay_seconds": {
            "type": "number",
            "description": (
                "Run once after this many seconds; add needs it unless "
                "every_seconds is given."
            ),
        },
        "job_id": {
            "type": "string",
            "description": "The job to remove; remove needs it.",
        },
    },
    "required": ["action"],
    "additionalProperties": False,
}


class CronTool:
    """Schedules, lists, and removes turns in the calling session.

    A job runs in the long-running host (``newbot serve``) and delivers to the
    conversation that created it; the tool says so, because a job created from a
    one-shot CLI run has no host to fire it.
    """

    def __init__(self, store: JobStorePort, *, clock: Clock = utcnow) -> None:
        self._store = store
        self._clock = clock
        self.spec = ToolSpec(
            name="cron",
            description=(
                "Schedule, list, or remove turns that run later in this conversation."
            ),
            parameters=_SCHEMA,
        )

    async def invoke(
        self, arguments: Mapping[str, object], ctx: ToolContext
    ) -> ToolOutput:
        action = require_string(arguments, "action")
        if action == "add":
            return await self._add(arguments, ctx)
        if action == "list":
            return await self._list()
        if action == "remove":
            return await self._remove(arguments)
        raise ToolError(f"unknown action {action!r}; expected add, list, or remove")

    async def _add(
        self, arguments: Mapping[str, object], ctx: ToolContext
    ) -> ToolOutput:
        prompt = require_string(arguments, "prompt")
        every = _positive_number(arguments, "every_seconds")
        delay = _positive_number(arguments, "delay_seconds")
        if every is not None and delay is None:
            seconds = every
        elif delay is not None and every is None:
            seconds = delay
        else:
            raise ToolError(
                "provide exactly one of 'every_seconds' or 'delay_seconds'"
            )
        job = await asyncio.to_thread(
            self._store.add,
            transport=ctx.session.transport,
            conversation=ctx.session.conversation,
            prompt=prompt,
            next_run_at=self._clock() + timedelta(seconds=seconds),
            every_seconds=every,
        )
        return ToolOutput(text=f"{_describe(job)}; jobs run while the host is serving")

    async def _list(self) -> ToolOutput:
        jobs = await asyncio.to_thread(self._store.jobs)
        if not jobs:
            return ToolOutput(text="no scheduled jobs")
        return ToolOutput(
            text="\n".join(
                f"- {job.id}  {_cadence(job)}  next {job.next_run_at.isoformat()}  "
                f"{job.prompt!r}"
                for job in jobs
            )
        )

    async def _remove(self, arguments: Mapping[str, object]) -> ToolOutput:
        job_id = require_string(arguments, "job_id")
        removed = await asyncio.to_thread(self._store.remove, job_id)
        return ToolOutput(
            text=f"removed {job_id}" if removed else f"no job {job_id!r}"
        )


def _positive_number(arguments: Mapping[str, object], key: str) -> float | None:
    value = arguments.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ToolError(f"argument {key!r} must be a number")
    if value <= 0:
        raise ToolError(f"argument {key!r} must be positive")
    return float(value)


def _describe(job: ScheduledJob) -> str:
    return f"scheduled {job.id} ({_cadence(job)}; next {job.next_run_at.isoformat()})"


def _cadence(job: ScheduledJob) -> str:
    if job.every_seconds is None:
        return "once"
    return f"every {job.every_seconds:g}s"
