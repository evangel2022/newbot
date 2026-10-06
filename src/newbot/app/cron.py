"""Dispatch due agent-created jobs into their bound sessions."""

from __future__ import annotations

import asyncio
import sys
from typing import TextIO

from newbot.adapters.stores.json_jobs import JsonJobStore
from newbot.domain.envelope import InboundEnvelope
from newbot.domain.errors import NewbotError
from newbot.domain.job import Clock, utcnow
from newbot.domain.turn import TurnStatus
from newbot.ports.transports import InboundHandler


class CronRunner:
    """Runs the due jobs of one workspace's schedule registry.

    The registry is advanced before a job's turn is submitted, so a crash or a
    failed turn never replays the run; a job that cannot run is reported and the
    next job in the same tick still runs.
    """

    def __init__(
        self,
        store: JsonJobStore,
        *,
        submit: InboundHandler,
        clock: Clock = utcnow,
        stderr: TextIO | None = None,
    ) -> None:
        self._store = store
        self._submit = submit
        self._clock = clock
        self._stderr = sys.stderr if stderr is None else stderr

    async def dispatch(self) -> int:
        """Run every due job once; return how many were dispatched."""
        jobs = await asyncio.to_thread(self._store.dispatch_due, self._clock())
        for job in jobs:
            try:
                status = await self._submit(
                    InboundEnvelope(
                        transport=job.transport,
                        conversation_id=job.conversation,
                        text=job.prompt,
                    )
                )
            except NewbotError as exc:
                self._warn(f"warning: scheduled job {job.id} failed: {exc}")
                continue
            if status is TurnStatus.FAILED:
                self._warn(f"warning: scheduled job {job.id} failed: turn failed")
        return len(jobs)

    def _warn(self, message: str) -> None:
        self._stderr.write(f"{message}\n")
        self._stderr.flush()
