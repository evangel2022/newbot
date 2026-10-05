"""Process lifecycle: one-shot and interactive turns return exit codes."""

from __future__ import annotations

import asyncio
import sys
from typing import TextIO

from newbot.adapters.curators.provider import ProviderCurator
from newbot.adapters.providers.registry import ProviderFactory, build_provider
from newbot.adapters.stores.fs_vault import FsVault
from newbot.adapters.stores.json_cursors import JsonCursors
from newbot.adapters.stores.jsonl_journal import JsonlJournal
from newbot.adapters.summarizers.provider import ProviderSummarizer
from newbot.adapters.transports.cli import CliTransport
from newbot.app.bootstrap import (
    build_runtime,
    build_sessions,
    resolve_workspace_root,
    vault_dir,
)
from newbot.config.schema import Settings
from newbot.domain.envelope import InboundEnvelope
from newbot.domain.session import SessionKey
from newbot.memory.curator import Curator
from newbot.memory.layout import MemoryLayout

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


async def run_compact(
    settings: Settings,
    *,
    keep_recent: int,
    stdout: TextIO | None = None,
    provider_factory: ProviderFactory = build_provider,
) -> int:
    """Fold a CLI session's older history into a summary checkpoint."""
    stream = sys.stdout if stdout is None else stdout
    provider = provider_factory(settings.provider)
    journal = JsonlJournal(MemoryLayout(resolve_workspace_root(settings)).journal)
    summary: str | None = None
    try:
        summary = await build_sessions(settings).compact(
            SessionKey(transport=CliTransport.transport_id, conversation=_CONVERSATION_ID),
            ProviderSummarizer(provider, model=settings.agent.model),
            keep_recent=keep_recent,
        )
        if summary is not None:
            await journal.append(summary)
    finally:
        await provider.aclose()
    stream.write("compacted\n" if summary is not None else "nothing to compact\n")
    return 0


async def run_curate(
    settings: Settings,
    *,
    stdout: TextIO | None = None,
    provider_factory: ProviderFactory = build_provider,
) -> int:
    """Run one curation pass over the workspace's durable memory files."""
    stream = sys.stdout if stdout is None else stdout
    provider = provider_factory(settings.provider)
    try:
        layout = MemoryLayout(resolve_workspace_root(settings))
        curator = Curator(
            layout=layout,
            journal=JsonlJournal(layout.journal),
            cursors=JsonCursors(layout.cursors),
            versioning=FsVault(vault_dir(settings), layout.workspace_root),
            interpreter=ProviderCurator(provider, model=settings.agent.model),
        )
        outcome = await curator.run()
    finally:
        await provider.aclose()
    if outcome.changed:
        stream.write(f"curated {', '.join(outcome.changed)}\n")
    else:
        stream.write("nothing to curate\n")
    return 0
