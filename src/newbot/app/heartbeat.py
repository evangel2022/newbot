"""Interpret the workspace heartbeat file as a list of active tasks."""

from __future__ import annotations

import re
from pathlib import Path

HEARTBEAT_FILE = "HEARTBEAT.md"
_ACTIVE_SECTION = "## Active Tasks"
_BULLET = re.compile(r"^[-*+]\s+(?P<task>\S.*)$")


def read_active_tasks(path: Path) -> tuple[str, ...]:
    """Return the top-level task bullets under ``## Active Tasks``.

    A missing file, an absent section, and a section without bullets all mean
    "nothing to check", which the heartbeat contract treats as a silent skip.
    """
    if not path.is_file():
        return ()
    return _parse_active_tasks(path.read_text(encoding="utf-8"))


def _parse_active_tasks(text: str) -> tuple[str, ...]:
    tasks: list[str] = []
    active = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            active = stripped == _ACTIVE_SECTION
            continue
        if not active:
            continue
        match = _BULLET.match(line)
        if match is not None:
            tasks.append(match.group("task").strip())
    return tuple(tasks)
