"""Contract tests for the maintenance scheduler."""

from __future__ import annotations

import asyncio

import pytest

from newbot.app.scheduler import Scheduler


async def test_scheduler_runs_a_job_repeatedly_until_cancelled() -> None:
    calls = 0
    enough = asyncio.Event()

    async def job() -> None:
        nonlocal calls
        calls += 1
        if calls >= 3:
            enough.set()

    scheduler = Scheduler()
    scheduler.every(0.01, job)
    task = asyncio.create_task(scheduler.run())
    try:
        await asyncio.wait_for(enough.wait(), timeout=2)
    finally:
        task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert calls >= 3


async def test_scheduler_without_jobs_waits_until_cancelled() -> None:
    scheduler = Scheduler()
    task = asyncio.create_task(scheduler.run())
    await asyncio.sleep(0)

    assert not task.done()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
