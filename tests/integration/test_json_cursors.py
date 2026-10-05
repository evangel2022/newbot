"""Integration tests for the curation cursor file."""

from __future__ import annotations

from pathlib import Path

import pytest

from newbot.adapters.stores.json_cursors import JsonCursors
from newbot.domain.errors import CurationError


async def test_missing_cursors_read_as_zero(tmp_path: Path) -> None:
    cursors = JsonCursors(tmp_path / "memory" / "cursors.json")

    assert await cursors.read() == 0


async def test_written_cursor_survives_a_new_instance(tmp_path: Path) -> None:
    path = tmp_path / "memory" / "cursors.json"
    await JsonCursors(path).write(7)

    assert await JsonCursors(path).read() == 7


async def test_malformed_cursors_raise_curation_error(tmp_path: Path) -> None:
    path = tmp_path / "memory" / "cursors.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"curation": -1}', encoding="utf-8")

    with pytest.raises(CurationError):
        await JsonCursors(path).read()
