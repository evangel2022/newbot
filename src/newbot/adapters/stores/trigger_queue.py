"""Durable, at-least-once queue of local trigger deliveries."""

from __future__ import annotations

import contextlib
import json
import os
import re
import secrets
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from newbot.domain.errors import TriggerError
from newbot.domain.trigger import TriggerDelivery

_DELIVERY_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")
_PENDING = "pending"
_RUNNING = "running"
_DONE = "done"
_FAILED = "failed"
_TERMINAL = frozenset({_DONE, _FAILED})


class _Record(BaseModel):
    """One delivery file, validated at the storage boundary."""

    model_config = ConfigDict(extra="forbid")

    delivery_id: str = Field(min_length=1)
    trigger_id: str = Field(min_length=1)
    conversation: str = Field(min_length=1)
    text: str = Field(min_length=1)
    state: str
    reason: str | None = None


class TriggerQueue:
    """Owns the durable delivery files for one host's local triggers.

    Deliveries are claimed and marked; a claimed-but-unfinished delivery is
    redelivered on the next claim (at-least-once), while a terminal delivery is
    never run again (deduplicated by delivery id).
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    def enqueue(
        self,
        trigger_id: str,
        conversation: str,
        text: str,
        *,
        delivery_id: str | None = None,
    ) -> str:
        """Write one pending delivery; an existing delivery id is not rewritten."""
        chosen = secrets.token_hex(8) if delivery_id is None else delivery_id
        if _DELIVERY_ID.fullmatch(chosen) is None:
            raise TriggerError(f"invalid delivery id {chosen!r}")
        path = self._root / f"{chosen}.json"
        if path.is_file():
            return chosen
        self._write(
            path,
            _Record(
                delivery_id=chosen,
                trigger_id=trigger_id,
                conversation=conversation,
                text=text,
                state=_PENDING,
            ),
        )
        return chosen

    def claim(self) -> tuple[TriggerDelivery, ...]:
        """Return the deliveries to run: pending work plus a crashed claim."""
        claims: list[TriggerDelivery] = []
        for path in sorted(self._root.glob("*.json")):
            record = self._read(path)
            if record is None or record.state in _TERMINAL:
                continue
            self._write(path, record.model_copy(update={"state": _RUNNING}))
            claims.append(
                TriggerDelivery(
                    delivery_id=record.delivery_id,
                    trigger_id=record.trigger_id,
                    conversation=record.conversation,
                    text=record.text,
                )
            )
        return tuple(claims)

    def complete(self, delivery_id: str) -> None:
        """Mark a claimed delivery as done."""
        self._finish(delivery_id, state=_DONE, reason=None)

    def fail(self, delivery_id: str, reason: str) -> None:
        """Mark a claimed delivery as failed so it is never retried."""
        self._finish(delivery_id, state=_FAILED, reason=reason)

    def _finish(self, delivery_id: str, *, state: str, reason: str | None) -> None:
        path = self._root / f"{delivery_id}.json"
        record = self._read(path)
        if record is None:
            return
        self._write(path, record.model_copy(update={"state": state, "reason": reason}))

    def _read(self, path: Path) -> _Record | None:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._quarantine(path)
            return None
        try:
            return _Record.model_validate(raw)
        except ValidationError:
            self._quarantine(path)
            return None

    def _write(self, path: Path, record: _Record) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.stem}.tmp")
        try:
            temp.write_text(json.dumps(record.model_dump()), encoding="utf-8")
            os.replace(temp, path)
        except OSError as exc:
            raise TriggerError(f"cannot write trigger delivery {path.name!r}") from exc

    def _quarantine(self, path: Path) -> None:
        with contextlib.suppress(OSError):
            path.replace(path.with_suffix(".invalid"))
