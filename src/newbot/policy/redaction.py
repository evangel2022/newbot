"""Bound and sanitize text before it enters model context (C7)."""

from __future__ import annotations

MAX_TOOL_RESULT_CHARS = 4000
_KEEP_CONTROL = {"\n", "\t"}


def bound_text(text: str, *, limit: int = MAX_TOOL_RESULT_CHARS) -> str:
    """Strip control characters and cap length, marking any truncation."""
    cleaned = "".join(
        char for char in text if char in _KEEP_CONTROL or char >= " "
    )
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[:limit]}\n...[truncated {len(cleaned) - limit} chars]"
