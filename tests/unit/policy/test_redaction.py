"""Tests for result bounding and sanitization (C7)."""

from __future__ import annotations

from newbot.policy.redaction import bound_text


def test_long_text_is_truncated_with_marker() -> None:
    result = bound_text("a" * 10, limit=4)

    assert result.startswith("aaaa")
    assert "truncated 6 chars" in result


def test_control_characters_are_stripped() -> None:
    assert bound_text("a\x00b\x07c") == "abc"


def test_newlines_and_tabs_are_kept() -> None:
    assert bound_text("a\n\tb") == "a\n\tb"
