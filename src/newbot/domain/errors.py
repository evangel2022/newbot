"""Typed error hierarchy for deliberate newbot failures."""

from __future__ import annotations


class NewbotError(Exception):
    """Base class for all deliberate newbot failures."""


class ConfigLoadError(NewbotError):
    """Configuration could not be loaded or is invalid."""

    def __init__(self, message: str, *, location: str | None = None) -> None:
        self.location = location
        if location is not None:
            message = f"{location}: {message}"
        super().__init__(message)


class ProviderError(NewbotError):
    """A provider call failed or returned an unusable response."""


class ToolError(NewbotError):
    """A tool failed with a deliberate, reportable error."""


class PathAccessDenied(ToolError):
    """A path was rejected by the workspace guard."""


class NetworkAccessDenied(ToolError):
    """An outbound URL was rejected by the network guard."""


class SessionError(NewbotError):
    """A session record could not be read, normalized, or written."""
