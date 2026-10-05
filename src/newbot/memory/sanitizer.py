"""C7 sanitization for text written to durable memory."""

from __future__ import annotations

from newbot.policy.redaction import Redactor, bound_text

MAX_SUMMARY_CHARS = 4000
MAX_DURABLE_CHARS = 64_000


def sanitize(text: str, redactor: Redactor, *, limit: int) -> str:
    """Redact known secrets and bound text before it enters durable memory."""
    return bound_text(redactor.redact(text), limit=limit)
