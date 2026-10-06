"""Durable JSON registry of subagent task records."""

from __future__ import annotations

import contextlib
import json
import os
import threading
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from newbot.domain.errors import SubagentError
from newbot.domain.session import SessionKey
from newbot.domain.subagent import SubagentStatus, SubagentTaskRecord

SUBAGENT_TASKS_DIRNAME = "subagents"
_TASKS_FILE = "tasks.json"
_QUARANTINE_FILE = "tasks.invalid.json"
_LOCK = threading.Lock()


class _Record(BaseModel):
    """One task record, validated at the storage boundary."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    transport: str = Field(min_length=1)
    conversation: str = Field(min_length=1)
    child_transport: str = Field(min_length=1)
    child_conversation: str = Field(min_length=1)
    status: SubagentStatus
    text: str = ""


class JsonSubagentTaskStore:
    """Owns one workspace's ``subagents/tasks.json`` registry.

    Writes are atomic so a crash never leaves a partial registry, and a
    registry that cannot be parsed is quarantined as ``tasks.invalid.json``
    (the ADR-018 policy) so one corrupt file cannot wedge every startup.
    """

    def __init__(self, root: Path) -> None:
        self._path = root / _TASKS_FILE

    def load(self) -> tuple[SubagentTaskRecord, ...]:
        """Return every stored task record."""
        with _LOCK:
            return tuple(_record(item) for item in self._load())

    def save(self, records: Sequence[SubagentTaskRecord]) -> None:
        """Replace the stored records with ``records``."""
        with _LOCK:
            try:
                stored = [_stored(record) for record in records]
            except ValidationError as exc:
                raise SubagentError(
                    f"cannot store a subagent task record: {exc}"
                ) from exc
            self._save(stored)

    def _load(self) -> list[_Record]:
        if not self._path.is_file():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            items = _items(raw)
            return [_Record.model_validate(item) for item in items]
        except (OSError, json.JSONDecodeError, ValidationError, SubagentError):
            self._quarantine()
            return []

    def _save(self, records: list[_Record]) -> None:
        payload = {"tasks": [record.model_dump(mode="json") for record in records]}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp = self._path.with_name(f".{self._path.name}.tmp")
        try:
            temp.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(temp, self._path)
        except OSError as exc:
            raise SubagentError("cannot write the subagent task registry") from exc

    def _quarantine(self) -> None:
        with contextlib.suppress(OSError):
            self._path.replace(self._path.with_name(_QUARANTINE_FILE))


def _items(raw: object) -> list[object]:
    if not isinstance(raw, dict):
        raise SubagentError("the subagent task registry must be a JSON object")
    items = raw.get("tasks")
    if not isinstance(items, list):
        raise SubagentError("the subagent task registry must hold a tasks list")
    return items


def _record(record: _Record) -> SubagentTaskRecord:
    return SubagentTaskRecord(
        id=record.id,
        parent=SessionKey(record.transport, record.conversation),
        child=SessionKey(record.child_transport, record.child_conversation),
        status=record.status,
        text=record.text,
    )


def _stored(record: SubagentTaskRecord) -> _Record:
    return _Record(
        id=record.id,
        transport=record.parent.transport,
        conversation=record.parent.conversation,
        child_transport=record.child.transport,
        child_conversation=record.child.conversation,
        status=record.status,
        text=record.text,
    )
