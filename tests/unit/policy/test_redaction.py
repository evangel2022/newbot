"""Tests for result bounding (C7) and secret redaction (S6)."""

from __future__ import annotations

from newbot.policy.redaction import Redactor, bound_text


def test_long_text_is_truncated_with_marker() -> None:
    result = bound_text("a" * 10, limit=4)

    assert result.startswith("aaaa")
    assert "truncated 6 chars" in result


def test_control_characters_are_stripped() -> None:
    assert bound_text("a\x00b\x07c") == "abc"


def test_newlines_and_tabs_are_kept() -> None:
    assert bound_text("a\n\tb") == "a\n\tb"


def test_known_secrets_are_redacted() -> None:
    redactor = Redactor(["sk-live-abcdef123456"])

    assert redactor.redact("token=sk-live-abcdef123456.") == "token=[redacted]."


def test_longer_secret_is_redacted_before_shorter_one() -> None:
    redactor = Redactor(["sk-abc12345", "sk-abc123456789"])

    assert redactor.redact("sk-abc123456789") == "[redacted]"


def test_short_values_are_not_treated_as_secrets() -> None:
    redactor = Redactor(["k"])

    assert redactor.redact("keep") == "keep"
