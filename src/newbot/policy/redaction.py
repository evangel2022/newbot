"""Bound, sanitize, and redact text before it enters model context (C7/S6)."""

from __future__ import annotations

from collections.abc import Iterable

MAX_TOOL_RESULT_CHARS = 4000
MIN_SECRET_LENGTH = 8
_PLACEHOLDER = "[redacted]"
_KEEP_CONTROL = {"\n", "\t"}


def bound_text(text: str, *, limit: int = MAX_TOOL_RESULT_CHARS) -> str:
    """Strip control characters and cap length, marking any truncation."""
    cleaned = "".join(
        char for char in text if char in _KEEP_CONTROL or char >= " "
    )
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[:limit]}\n...[truncated {len(cleaned) - limit} chars]"


class Redactor:
    """Replaces known secret values with a placeholder (S6).

    Values shorter than ``MIN_SECRET_LENGTH`` are ignored: replacing a short
    string would corrupt unrelated text without protecting a real secret.
    """

    def __init__(self, secrets: Iterable[str]) -> None:
        unique = {secret for secret in secrets if len(secret) >= MIN_SECRET_LENGTH}
        self._secrets = tuple(sorted(unique, key=lambda secret: (-len(secret), secret)))

    def redact(self, text: str) -> str:
        """Replace every occurrence of a known secret with the placeholder.

        Longer secrets are removed first so a secret nested inside another is
        not left partially exposed.
        """
        for secret in self._secrets:
            text = text.replace(secret, _PLACEHOLDER)
        return text
