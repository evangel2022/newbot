"""Durable JSON registry of agent-created scheduled jobs."""

from __future__ import annotations

import contextlib
import json
import os
import re
import secrets
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from newbot.domain.errors import CronError
from newbot.domain.job import ScheduledJob

JOBS_DIRNAME = "cron"
_JOBS_FILE = "jobs.json"
_QUARANTINE_FILE = "jobs.invalid.json"
_JOB_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")
_LOCK = threading.Lock()


class _Record(BaseModel):
    """One job, validated at the storage boundary."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    transport: str = Field(min_length=1)
    conversation: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    next_run_at: datetime
    every_seconds: float | None = Field(default=None, gt=0)

    @field_validator("next_run_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("next_run_at must carry a timezone")
        return value.astimezone(UTC)


class JsonJobStore:
    """Owns one workspace's ``cron/jobs.json`` registry.

    Every operation is a read-modify-write of that single file, serialized by a
    process-wide lock so the scheduling tool and the host poller cannot lose an
    update, and written atomically so a crash never leaves a partial registry. A
    registry that cannot be parsed is quarantined as ``jobs.invalid.json`` (the
    ADR-018 delivery-file policy) so one corrupt file cannot wedge every poll.
    """

    def __init__(self, root: Path) -> None:
        self._path = root / _JOBS_FILE

    def jobs(self) -> tuple[ScheduledJob, ...]:
        """Return every scheduled job."""
        with _LOCK:
            return tuple(_job(record) for record in self._load())

    def add(
        self,
        *,
        transport: str,
        conversation: str,
        prompt: str,
        next_run_at: datetime,
        every_seconds: float | None = None,
    ) -> ScheduledJob:
        """Append one job and return it."""
        try:
            record = _Record(
                id=secrets.token_hex(4),
                transport=transport,
                conversation=conversation,
                prompt=prompt,
                next_run_at=next_run_at,
                every_seconds=every_seconds,
            )
        except ValidationError as exc:
            raise CronError(f"cannot store the scheduled job: {exc}") from exc
        with _LOCK:
            records = self._load()
            records.append(record)
            self._save(records)
        return _job(record)

    def remove(self, job_id: str) -> bool:
        """Drop one job; return whether it existed."""
        if _JOB_ID.fullmatch(job_id) is None:
            raise CronError(f"invalid job id {job_id!r}")
        with _LOCK:
            records = self._load()
            kept = [record for record in records if record.id != job_id]
            if len(kept) == len(records):
                return False
            self._save(kept)
        return True

    def dispatch_due(self, now: datetime) -> tuple[ScheduledJob, ...]:
        """Return the jobs that are due and advance or drop them.

        The registry is updated before the caller runs the turn, so a crash or a
        failed turn never replays a run. A recurring job's next run is ``now``
        plus its interval, which skips runs missed while the host was down; a
        one-shot job that is overdue runs on the next dispatch and is dropped.
        """
        with _LOCK:
            records = self._load()
            due: list[_Record] = []
            remaining: list[_Record] = []
            for record in records:
                if record.next_run_at > now:
                    remaining.append(record)
                    continue
                due.append(record)
                if record.every_seconds is not None:
                    remaining.append(
                        record.model_copy(
                            update={
                                "next_run_at": now
                                + timedelta(seconds=record.every_seconds)
                            }
                        )
                    )
            if due:
                self._save(remaining)
        return tuple(_job(record) for record in due)

    def _load(self) -> list[_Record]:
        if not self._path.is_file():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            items = _items(raw)
            return [_Record.model_validate(item) for item in items]
        except (OSError, json.JSONDecodeError, ValidationError, CronError):
            self._quarantine()
            return []

    def _save(self, records: list[_Record]) -> None:
        payload = {"jobs": [record.model_dump(mode="json") for record in records]}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp = self._path.with_name(f".{self._path.name}.tmp")
        try:
            temp.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(temp, self._path)
        except OSError as exc:
            raise CronError("cannot write the job registry") from exc

    def _quarantine(self) -> None:
        with contextlib.suppress(OSError):
            self._path.replace(self._path.with_name(_QUARANTINE_FILE))


def _items(raw: object) -> list[object]:
    if not isinstance(raw, dict):
        raise CronError("the job registry must be a JSON object")
    items = raw.get("jobs")
    if not isinstance(items, list):
        raise CronError("the job registry must hold a jobs list")
    return items


def _job(record: _Record) -> ScheduledJob:
    return ScheduledJob(
        id=record.id,
        transport=record.transport,
        conversation=record.conversation,
        prompt=record.prompt,
        next_run_at=record.next_run_at,
        every_seconds=record.every_seconds,
    )
