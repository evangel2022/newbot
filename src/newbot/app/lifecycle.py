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
    Runtime,
    build_runtime,
    build_sessions,
    configured_secrets,
    resolve_workspace_root,
    vault_dir,
)
from newbot.config.schema import Settings
from newbot.domain.envelope import InboundEnvelope
from newbot.domain.errors import NewbotError, VersionError
from newbot.domain.session import SessionKey
from newbot.memory.consolidator import Consolidator
from newbot.memory.curator import Curator
from newbot.memory.layout import MemoryLayout
from newbot.policy.redaction import Redactor
from newbot.session.manager import SessionManager

_CONVERSATION_ID = "default"
_EXIT_COMMANDS = frozenset({"/exit", "/quit"})
_PROMPT = "you> "
DEFAULT_KEEP_RECENT = 8
_COMMANDS_HELP = (
    "commands:\n"
    "  /compact  summarize older history into a checkpoint\n"
    "  /curate   fold new summaries into durable memory files\n"
    "  /help     show this help\n"
    "  /exit     leave the session\n"
)


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
        await _auto_compact(settings, runtime, stderr=stderr)
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
    conversation). A line starting with ``/`` is a session command. A failed
    turn is reported and the loop continues.
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
            if text.startswith("/"):
                await _run_command(
                    text,
                    runtime=runtime,
                    settings=settings,
                    stream=prompt,
                    provider_factory=provider_factory,
                )
                continue
            await runtime.hub.submit(
                InboundEnvelope(
                    transport=runtime.transport.transport_id,
                    conversation_id=_CONVERSATION_ID,
                    text=text,
                )
            )
            await _auto_compact(settings, runtime, stderr=stderr)
    finally:
        await runtime.provider.aclose()
    return 0


async def _run_command(
    command: str,
    *,
    runtime: Runtime,
    settings: Settings,
    stream: TextIO,
    provider_factory: ProviderFactory,
) -> None:
    """Run an interactive session command against the live runtime."""
    if command == "/compact":
        await _compact_session(
            settings,
            runtime.sessions,
            keep_recent=DEFAULT_KEEP_RECENT,
            stream=stream,
            provider_factory=provider_factory,
        )
    elif command == "/curate":
        await _curate_memory(settings, stream=stream, provider_factory=provider_factory)
    elif command == "/help":
        stream.write(_COMMANDS_HELP)
    else:
        stream.write(f"unknown command: {command}\n")


async def _compact_session(
    settings: Settings,
    sessions: SessionManager,
    *,
    keep_recent: int,
    stream: TextIO,
    provider_factory: ProviderFactory,
) -> None:
    """Fold older session history into a checkpoint and journal its summary."""
    provider = provider_factory(settings.provider)
    summary: str | None = None
    try:
        summary = await sessions.compact(
            _cli_session_key(),
            ProviderSummarizer(provider, model=settings.agent.model),
            keep_recent=keep_recent,
        )
        if summary is not None:
            await _build_consolidator(settings).consolidate(summary)
    finally:
        await provider.aclose()
    stream.write("compacted\n" if summary is not None else "nothing to compact\n")


async def _auto_compact(
    settings: Settings, runtime: Runtime, *, stderr: TextIO | None
) -> None:
    """Compact a saturated session after a turn.

    Compaction is maintenance on a turn that already succeeded, so a failure is
    reported to the operator and the completed turn keeps its result.
    """
    try:
        summary = await runtime.sessions.compact_when_saturated(
            _cli_session_key(),
            ProviderSummarizer(runtime.provider, model=settings.agent.model),
        )
        if summary is not None:
            await _build_consolidator(settings).consolidate(summary)
    except NewbotError as exc:
        stream = sys.stderr if stderr is None else stderr
        stream.write(f"warning: session compaction failed: {exc}\n")


def _cli_session_key() -> SessionKey:
    return SessionKey(transport=CliTransport.transport_id, conversation=_CONVERSATION_ID)


def _build_consolidator(settings: Settings) -> Consolidator:
    layout = MemoryLayout(resolve_workspace_root(settings))
    return Consolidator(
        journal=JsonlJournal(layout.journal),
        redactor=Redactor(configured_secrets(settings)),
    )


async def run_compact(
    settings: Settings,
    *,
    keep_recent: int,
    stdout: TextIO | None = None,
    provider_factory: ProviderFactory = build_provider,
) -> int:
    """Fold a CLI session's older history into a summary checkpoint."""
    stream = sys.stdout if stdout is None else stdout
    await _compact_session(
        settings,
        build_sessions(settings),
        keep_recent=keep_recent,
        stream=stream,
        provider_factory=provider_factory,
    )
    return 0


async def _curate_memory(
    settings: Settings,
    *,
    stream: TextIO,
    provider_factory: ProviderFactory,
) -> None:
    """Run one curation pass over the workspace's durable memory files."""
    provider = provider_factory(settings.provider)
    try:
        layout = MemoryLayout(resolve_workspace_root(settings))
        curator = Curator(
            layout=layout,
            journal=JsonlJournal(layout.journal),
            cursors=JsonCursors(layout.cursors),
            versioning=FsVault(vault_dir(settings), layout.workspace_root),
            redactor=Redactor(configured_secrets(settings)),
            interpreter=ProviderCurator(provider, model=settings.agent.model),
        )
        outcome = await curator.run()
    finally:
        await provider.aclose()
    if outcome.changed:
        stream.write(f"curated {', '.join(outcome.changed)}\n")
        if outcome.change_set is not None:
            stream.write(f"change-set {outcome.change_set}\n")
    else:
        stream.write("nothing to curate\n")


async def run_curate(
    settings: Settings,
    *,
    stdout: TextIO | None = None,
    provider_factory: ProviderFactory = build_provider,
) -> int:
    """Run one curation pass over the workspace's durable memory files."""
    stream = sys.stdout if stdout is None else stdout
    await _curate_memory(settings, stream=stream, provider_factory=provider_factory)
    return 0


async def run_memory_log(settings: Settings, *, stdout: TextIO | None = None) -> int:
    """Print recorded durable-memory versions, newest first."""
    stream = sys.stdout if stdout is None else stdout
    layout = MemoryLayout(resolve_workspace_root(settings))
    versions = await FsVault(vault_dir(settings), layout.workspace_root).versions()
    if not versions:
        stream.write("no memory versions\n")
        return 0
    for version in versions:
        stream.write(
            f"{version.version_id}  {version.path}  "
            f"{version.timestamp.isoformat()}  {version.size}  "
            f"{version.change_set or '-'}\n"
        )
    return 0


async def run_memory_restore(
    settings: Settings, *, version_id: str, stdout: TextIO | None = None
) -> int:
    """Write a recorded version back to its durable file."""
    stream = sys.stdout if stdout is None else stdout
    layout = MemoryLayout(resolve_workspace_root(settings))
    vault = FsVault(vault_dir(settings), layout.workspace_root)
    match = next(
        (
            version
            for version in await vault.versions()
            if version.version_id == version_id
        ),
        None,
    )
    if match is None:
        raise VersionError(f"unknown memory version: {version_id}")
    await vault.restore(layout.workspace_root / match.path, version_id)
    stream.write(f"restored {match.path} to {version_id}\n")
    return 0


async def run_memory_revert_set(
    settings: Settings, *, change_set: str, stdout: TextIO | None = None
) -> int:
    """Undo one change-set, returning each file to its previous version."""
    stream = sys.stdout if stdout is None else stdout
    layout = MemoryLayout(resolve_workspace_root(settings))
    vault = FsVault(vault_dir(settings), layout.workspace_root)
    reverted = await vault.revert_set(change_set)
    stream.write(f"restored {', '.join(reverted)} to change-set {change_set}\n")
    return 0
