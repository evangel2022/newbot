"""Cursor file tracking how far curation has consumed the journal."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from newbot.domain.errors import CurationError


class _WireCursors(BaseModel):
    model_config = ConfigDict(extra="forbid")

    curation: int = Field(ge=0)


class JsonCursors:
    """Stores the curation cursor as a small JSON object."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = asyncio.Lock()

    async def read(self) -> int:
        async with self._lock:
            return await asyncio.to_thread(self._read)

    async def write(self, cursor: int) -> None:
        async with self._lock:
            await asyncio.to_thread(self._write, cursor)

    def _read(self) -> int:
        try:
            text = (
                self._path.read_text(encoding="utf-8") if self._path.is_file() else ""
            )
        except OSError as exc:
            raise CurationError(
                f"cannot read cursors {self._path.name}: {exc}"
            ) from exc
        if not text.strip():
            return 0
        try:
            return _WireCursors.model_validate_json(text).curation
        except (ValidationError, ValueError) as exc:
            raise CurationError(
                f"invalid cursors {self._path.name}: {exc}"
            ) from exc

    def _write(self, cursor: int) -> None:
        payload = json.dumps({"curation": cursor})
        try:
            _atomic_write_text(self._path, payload)
        except OSError as exc:
            raise CurationError(
                f"cannot write cursors {self._path.name}: {exc}"
            ) from exc


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle_fd, temp_name = tempfile.mkstemp(
        dir=path.parent, prefix=path.name, suffix=".tmp"
    )
    try:
        with os.fdopen(handle_fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(temp_name, path)
    except OSError:
        Path(temp_name).unlink(missing_ok=True)
        raise
