"""Process lifecycle: run a one-shot turn and return an exit code."""

from __future__ import annotations

from typing import TextIO

from newbot.adapters.providers.registry import ProviderFactory, build_provider
from newbot.app.bootstrap import build_runtime
from newbot.config.schema import Settings
from newbot.domain.envelope import InboundEnvelope


async def run_once(
    settings: Settings,
    message: str,
    *,
    provider_factory: ProviderFactory = build_provider,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run a single turn on the CLI transport; return a process exit code."""
    runtime = build_runtime(
        settings, provider_factory=provider_factory, stdout=stdout, stderr=stderr
    )
    try:
        await runtime.hub.submit(
            InboundEnvelope(
                transport=runtime.transport.transport_id,
                conversation_id="default",
                text=message,
            )
        )
    finally:
        await runtime.provider.aclose()
    return runtime.transport.exit_code
