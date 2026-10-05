"""Provider factory: maps configuration to a concrete provider class."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeAlias

from newbot.adapters.providers.openai_compatible import OpenAICompatibleProvider
from newbot.config.schema import ProviderSettings
from newbot.domain.errors import ConfigLoadError
from newbot.ports.provider import ProviderPort

ProviderFactory: TypeAlias = Callable[[ProviderSettings], ProviderPort]


def build_provider(settings: ProviderSettings) -> ProviderPort:
    """Construct the provider named by configuration, or fail with a located error."""
    if settings.name == "openai_compatible":
        return OpenAICompatibleProvider(settings)
    raise ConfigLoadError(
        f"unknown provider {settings.name!r}", location="provider.name"
    )
