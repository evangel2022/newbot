"""Value types crossing the provider boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from newbot.domain.message import Message
from newbot.domain.tool import ToolSpec


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """A provider-ready model call."""

    model: str
    system: str
    messages: tuple[Message, ...]
    tools: tuple[ToolSpec, ...] = ()


@dataclass(frozen=True, slots=True)
class TextDelta:
    """An incremental piece of assistant text."""

    text: str


@dataclass(frozen=True, slots=True)
class Completed:
    """The final, authoritative message of a provider stream."""

    message: Message


StreamEvent: TypeAlias = TextDelta | Completed
