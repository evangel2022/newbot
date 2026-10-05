"""Process lifecycle: one-shot and interactive turns return exit codes."""

from __future__ import annotations

import asyncio
import sys
from typing import TextIO

from newbot.adapters.providers.registry import ProviderFactory, build_provider
from newbot.app.bootstrap import build_runtime
from newbot.config.schema import Settings
from newbot.domain.envelope import InboundEnvelope

_CONVERSATION_ID = "default"
_EXIT_COMMANDS = frozenset({"/exit", "/quit"})
_PROMPT = "you> "


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
                conversation_id=_CONVERSATION_ID,
                text=message,
            )
        )
    finally:
        await runtime.provider.aclose()
    return runtime.transport.exit_code


async def run_interactive(
    settings: Settings,
    *,
    stdin: TextIO,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    provider_factory: ProviderFactory = build_provider,
) -> int:
    """Run an interactive terminal session until EOF or an exit command.

    Every line becomes one turn in a single persistent session, so history
    accumulates during the process and across ``newbot run`` (same
    conversation). A failed turn is reported and the loop continues.
    """
    runtime = build_runtime(
        settings, provider_factory=provider_factory, stdout=stdout, stderr=stderr
    )
    prompt = sys.stdout if stdout is None else stdout
    try:
        while True:
            prompt.write(_PROMPT)
            prompt.flush()
            line = await asyncio.to_thread(stdin.readline)
            if not line:
                break
            text = line.strip()
            if text in _EXIT_COMMANDS:
                break
            if not text:
                continue
            await runtime.hub.submit(
                InboundEnvelope(
                    transport=runtime.transport.transport_id,
                    conversation_id=_CONVERSATION_ID,
                    text=text,
                )
            )
    finally:
        await runtime.provider.aclose()
    return 0
