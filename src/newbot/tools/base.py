"""Tool contract and argument helpers."""

from __future__ import annotations

from collections.abc import Mapping

from newbot.domain.errors import ToolError
from newbot.ports.tools import Tool, ToolOutput

__all__ = ["Tool", "ToolOutput", "require_string"]


def require_string(arguments: Mapping[str, object], key: str) -> str:
    """Return a required non-empty string argument or raise ``ToolError``."""
    value = arguments.get(key)
    if not isinstance(value, str) or not value:
        raise ToolError(f"argument {key!r} must be a non-empty string")
    return value
