"""Value types crossing the curation boundary."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DurableFile:
    """The current content of one long-term memory file."""

    path: str
    content: str


@dataclass(frozen=True, slots=True)
class CurationEdit:
    """A proposed new content for one long-term memory file."""

    path: str
    content: str


@dataclass(frozen=True, slots=True)
class CurationOutcome:
    """What one curation pass consumed and changed."""

    changed: tuple[str, ...]
    consumed: int
    change_set: str | None = None
