"""Run workspace maintenance jobs on a timer until the host shuts down."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

Job = Callable[[], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class _Scheduled:
    interval: float
    job: Job


class Scheduler:
    """Runs each registered job on its own interval until cancelled.

    A job is never started while its previous run is still in flight: the loop
    sleeps, runs, then sleeps again, so a slow job delays its own next tick
    instead of overlapping itself.
    """

    def __init__(self) -> None:
        self._jobs: list[_Scheduled] = []

    def every(self, interval: float, job: Job) -> None:
        """Register ``job`` to run every ``interval`` seconds."""
        self._jobs.append(_Scheduled(interval=interval, job=job))

    async def run(self) -> None:
        """Run every registered job until this coroutine is cancelled."""
        async with asyncio.TaskGroup() as group:
            for scheduled in self._jobs:
                group.create_task(_run_forever(scheduled))
            await asyncio.Event().wait()


async def _run_forever(scheduled: _Scheduled) -> None:
    while True:
        await asyncio.sleep(scheduled.interval)
        await scheduled.job()
