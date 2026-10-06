"""Value types for workspace skills (markdown know-how)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Skill:
    """One loaded skill: its name, one-line summary, and full instructions."""

    name: str
    description: str
    body: str
