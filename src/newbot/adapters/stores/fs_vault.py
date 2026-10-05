"""Content-addressed, restorable versions of workspace files."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from newbot.domain.errors import VersionError
from newbot.domain.version import FileVersion

_INDEX_NAME = "index.jsonl"
_BLOBS_DIR = "blobs"
_VERSION_LENGTH = 16
_VERSION_PATTERN = re.compile(rf"[0-9a-f]{{{_VERSION_LENGTH}}}")


class _WireVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: str
    path: str
    timestamp: datetime
    size: int


class FsVault:
    """Records versions under ``base_dir``, outside the workspace tree.

    Keeping history out of the workspace means filesystem tools running inside the
    workspace cannot read or rewrite it.
    """

    def __init__(self, base_dir: Path, workspace_root: Path) -> None:
        self._base = base_dir
        self._root = workspace_root.resolve()
        self._lock = asyncio.Lock()

    async def write(self, path: Path, content: str) -> str:
        async with self._lock:
            return await asyncio.to_thread(self._write, path, content)

    async def history(self, path: Path) -> tuple[FileVersion, ...]:
        async with self._lock:
            return await asyncio.to_thread(self._history, path)

    async def versions(self) -> tuple[FileVersion, ...]:
        async with self._lock:
            return await asyncio.to_thread(self._versions)

    async def read(self, path: Path, version_id: str) -> str:
        async with self._lock:
            return await asyncio.to_thread(self._read, path, version_id)

    async def restore(self, path: Path, version_id: str) -> None:
        async with self._lock:
            await asyncio.to_thread(self._restore, path, version_id)

    def _write(self, path: Path, content: str) -> str:
        relative = self._relative(path)
        version_id = _digest(relative, content)
        self._store_version(relative, version_id, content)
        self._write_file(path, content, relative)
        return version_id

    def _restore(self, path: Path, version_id: str) -> None:
        relative = self._relative(path)
        content = self._read(path, version_id)
        self._store_version(relative, version_id, content)
        self._write_file(path, content, relative)

    def _history(self, path: Path) -> tuple[FileVersion, ...]:
        relative = self._relative(path)
        return tuple(
            version
            for version in reversed(self._read_index())
            if version.path == relative
        )

    def _versions(self) -> tuple[FileVersion, ...]:
        return tuple(reversed(self._read_index()))

    def _read(self, path: Path, version_id: str) -> str:
        relative = self._relative(path)
        if not any(
            version.path == relative and version.version_id == version_id
            for version in self._read_index()
        ):
            raise VersionError(f"unknown version for {relative}: {version_id}")
        blob = self._blob_path(version_id)
        try:
            return blob.read_text(encoding="utf-8")
        except OSError as exc:
            raise VersionError(f"cannot read version {version_id}: {exc}") from exc

    def _store_version(self, relative: str, version_id: str, content: str) -> None:
        latest = next(
            (
                version
                for version in reversed(self._read_index())
                if version.path == relative
            ),
            None,
        )
        if latest is not None and latest.version_id == version_id:
            return
        blob = self._blob_path(version_id)
        try:
            blob.parent.mkdir(parents=True, exist_ok=True)
            if not blob.is_file():
                blob.write_text(content, encoding="utf-8", newline="\n")
            self._append_index(
                FileVersion(
                    version_id=version_id,
                    path=relative,
                    timestamp=datetime.now(UTC),
                    size=len(content),
                )
            )
        except OSError as exc:
            raise VersionError(f"cannot record version for {relative}: {exc}") from exc

    def _write_file(self, path: Path, content: str, relative: str) -> None:
        try:
            _atomic_write_text(path, content)
        except OSError as exc:
            raise VersionError(f"cannot write {relative}: {exc}") from exc

    def _relative(self, path: Path) -> str:
        resolved = path.resolve()
        if not resolved.is_relative_to(self._root):
            raise VersionError(f"path is outside the workspace: {path}")
        return resolved.relative_to(self._root).as_posix()

    def _blob_path(self, version_id: str) -> Path:
        if _VERSION_PATTERN.fullmatch(version_id) is None:
            raise VersionError(f"malformed version id: {version_id!r}")
        return self._base / _BLOBS_DIR / version_id

    def _read_index(self) -> tuple[FileVersion, ...]:
        index = self._base / _INDEX_NAME
        try:
            text = index.read_text(encoding="utf-8") if index.is_file() else ""
        except OSError as exc:
            raise VersionError(f"cannot read version index: {exc}") from exc
        versions: list[FileVersion] = []
        for number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            versions.append(_parse_version(line, number))
        return tuple(versions)

    def _append_index(self, version: FileVersion) -> None:
        payload = json.dumps(
            {
                "version_id": version.version_id,
                "path": version.path,
                "timestamp": version.timestamp.isoformat(),
                "size": version.size,
            },
            ensure_ascii=False,
        )
        index = self._base / _INDEX_NAME
        index.parent.mkdir(parents=True, exist_ok=True)
        with index.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(f"{payload}\n")


def _digest(relative: str, content: str) -> str:
    payload = f"{relative}\x00{content}".encode()
    return hashlib.sha256(payload).hexdigest()[:_VERSION_LENGTH]


def _parse_version(line: str, number: int) -> FileVersion:
    try:
        wire = _WireVersion.model_validate_json(line)
    except (ValidationError, ValueError) as exc:
        raise VersionError(f"invalid version index line {number}: {exc}") from exc
    return FileVersion(
        version_id=wire.version_id,
        path=wire.path,
        timestamp=wire.timestamp,
        size=wire.size,
    )


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
