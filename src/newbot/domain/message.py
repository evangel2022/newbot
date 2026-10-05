"""Message value types shared by every layer."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from newbot.domain.tool import ToolCall


class Role(StrEnum):
    """Author of a message in a model conversation."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True, slots=True)
class Message:
    """One normalized message in a model conversation."""

    role: Role
    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
