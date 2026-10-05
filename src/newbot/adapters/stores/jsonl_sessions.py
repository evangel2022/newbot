"""JSONL session store with atomic replacement writes."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from newbot.domain.errors import SessionError
from newbot.domain.message import Message, Role
from newbot.domain.session import SessionKey, SessionRecord
from newbot.domain.tool import ToolCall

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_SLUG = 64


class _WireToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    arguments: str


class _WireMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Role
    content: str
    tool_calls: list[_WireToolCall] = []
    tool_call_id: str | None = None


class _WireRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    message: _WireMessage


class JsonlSessionStore:
    """Stores one append-only JSONL file per session under a base directory."""

    def __init__(self, base_dir: Path) -> None:
        self._base = base_dir

    async def load(
        self, workspace_id: str, key: SessionKey
    ) -> tuple[SessionRecord, ...]:
        return await asyncio.to_thread(self._load, workspace_id, key)

    async def append(
        self, workspace_id: str, key: SessionKey, records: Sequence[SessionRecord]
    ) -> None:
        if not records:
            return
        await asyncio.to_thread(self._append, workspace_id, key, tuple(records))

    def _load(self, workspace_id: str, key: SessionKey) -> tuple[SessionRecord, ...]:
        path = self._path(workspace_id, key)
        try:
            text = path.read_text(encoding="utf-8") if path.is_file() else ""
        except OSError as exc:
            raise SessionError(f"cannot read session file {path.name}: {exc}") from exc
        records: list[SessionRecord] = []
        for number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            records.append(_parse_record(line, path.name, number))
        return tuple(records)

    def _append(
        self, workspace_id: str, key: SessionKey, records: Sequence[SessionRecord]
    ) -> None:
        path = self._path(workspace_id, key)
        try:
            existing = (
                path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
            )
            lines = [line for line in existing if line.strip()]
            lines.extend(_serialize_record(record) for record in records)
            _atomic_write_lines(path, lines)
        except OSError as exc:
            raise SessionError(f"cannot write session file {path.name}: {exc}") from exc

    def _path(self, workspace_id: str, key: SessionKey) -> Path:
        workspace_dir = self._base / _slugged("ws", workspace_id)
        label = f"{key.transport}\x1f{key.conversation}"
        return workspace_dir / f"{_slugged('s', label)}.jsonl"


def _parse_record(line: str, filename: str, number: int) -> SessionRecord:
    try:
        wire = _WireRecord.model_validate_json(line)
    except (ValidationError, ValueError) as exc:
        raise SessionError(f"invalid record in {filename} line {number}: {exc}") from exc
    message = Message(
        role=wire.message.role,
        content=wire.message.content,
        tool_calls=tuple(
            ToolCall(id=call.id, name=call.name, arguments=call.arguments)
            for call in wire.message.tool_calls
        ),
        tool_call_id=wire.message.tool_call_id,
    )
    return SessionRecord(timestamp=wire.timestamp, message=message)


def _serialize_record(record: SessionRecord) -> str:
    message: dict[str, object] = {
        "role": record.message.role.value,
        "content": record.message.content,
    }
    if record.message.tool_calls:
        message["tool_calls"] = [
            {"id": call.id, "name": call.name, "arguments": call.arguments}
            for call in record.message.tool_calls
        ]
    if record.message.tool_call_id is not None:
        message["tool_call_id"] = record.message.tool_call_id
    payload: dict[str, object] = {"timestamp": record.timestamp, "message": message}
    payload["timestamp"] = record.timestamp.isoformat()
    return json.dumps(payload, ensure_ascii=False)


def _slugged(prefix: str, raw: str) -> str:
    slug = _UNSAFE.sub("-", raw).strip("-")[:_MAX_SLUG] or "session"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]
    return f"{prefix}-{slug}-{digest}"


def _atomic_write_lines(path: Path, lines: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle_fd, temp_name = tempfile.mkstemp(
        dir=path.parent, prefix=path.name, suffix=".tmp"
    )
    try:
        with os.fdopen(handle_fd, "w", encoding="utf-8", newline="\n") as handle:
            for line in lines:
                handle.write(f"{line}\n")
        os.replace(temp_name, path)
    except OSError:
        Path(temp_name).unlink(missing_ok=True)
        raise
