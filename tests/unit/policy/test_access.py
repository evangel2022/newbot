"""Contract tests for transport access control."""

from __future__ import annotations

from newbot.policy.access import AccessPolicy


def test_configured_token_authorizes_only_the_matching_bearer() -> None:
    access = AccessPolicy("s3cret-token")

    assert access.mutating_enabled is True
    assert access.allows("Bearer s3cret-token") is True
    assert access.allows("Bearer wrong-token") is False
    assert access.allows("s3cret-token") is False
    assert access.allows(None) is False


def test_unset_token_disables_mutation_entirely() -> None:
    access = AccessPolicy(None)

    assert access.mutating_enabled is False
    assert access.allows("Bearer anything") is False
