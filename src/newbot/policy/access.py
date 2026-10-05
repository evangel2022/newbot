"""Transport access control (S5): tokens gate every mutating request."""

from __future__ import annotations

import hmac

_BEARER = "Bearer "


class AccessPolicy:
    """Decides whether a transport request may mutate runtime state.

    An unset token disables mutation entirely: a transport must never run
    unauthenticated work just because no credential was configured.
    """

    def __init__(self, token: str | None) -> None:
        self._token = token

    @property
    def mutating_enabled(self) -> bool:
        """Whether a token is configured, so mutations may be authorized."""
        return self._token is not None

    def allows(self, authorization: str | None) -> bool:
        """Return whether an ``Authorization`` header carries the configured token."""
        if self._token is None:
            return False
        if authorization is None or not authorization.startswith(_BEARER):
            return False
        return hmac.compare_digest(authorization[len(_BEARER) :], self._token)
