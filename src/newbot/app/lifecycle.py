"""Process lifecycle: one-shot and interactive turns return exit codes."""

from __future__ import annotations

import asyncio
import contextlib
import sys
from typing import TextIO

from newbot.adapters.curators.provider import ProviderCurator
from newbot.adapters.providers.registry import ProviderFactory, build_provider
from newbot.adapters.stores.fs_vault import FsVault
from newbot.adapters.stores.json_cursors import JsonCursors
from newbot.adapters.stores.jsonl_journal import JsonlJournal
from newbot.adapters.summarizers.provider import ProviderSummarizer
from newbot.adapters.transports.cli import CliTransport
from newbot.adapters.transports.connectors.telegram import TelegramConnector
from newbot.adapters.transports.http_ws import WorkbenchServer
from newbot.app.bootstrap import (
    Runtime,
    build_runtime,
    build_sessions,
    build_trigger_queue,
    configured_secrets,
    resolve_workspace_root,
    vault_dir,
)
from newbot.app.cron import CronRunner
from newbot.app.heartbeat import HEARTBEAT_FILE, read_active_tasks
from newbot.app.scheduler import Job, Scheduler
from newbot.app.triggers import TriggerConsumer
from newbot.config.schema import ScheduledTurn, Settings
from newbot.domain.curation import CurationOutcome
from newbot.domain.envelope import InboundEnvelope
from newbot.domain.errors import NewbotError, TriggerError, VersionError
from newbot.domain.session import SessionKey
from newbot.domain.turn import TurnStatus
from newbot.memory.consolidator import Consolidator
from newbot.memory.curator import Curator
from newbot.memory.layout import MemoryLayout
from newbot.policy.access import AccessPolicy
from newbot.policy.redaction import Redactor
from newbot.ports.provider import ProviderPort
from newbot.session.manager import SessionManager

_CONVERSATION_ID = "default"
_EXIT_COMMANDS = frozenset({"/exit", "/quit"})
_PROMPT = "you> "
DEFAULT_KEEP_RECENT = 8
_CRON_POLL_SECONDS = 1.0
_COMMANDS_HELP = (
    "commands:\n"
    "  /compact  summarize older history into a checkpoint\n"
    "  /curate   fold new summaries into durable memory files\n"
    "  /new      stop this session's tasks and start it over\n"
    "  /stop     stop this session's running subagent tasks\n"
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
    runtime = await build_runtime(
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
        await runtime.subagents.drain()
        await runtime.aclose()
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
    runtime = await build_runtime(
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
        await runtime.subagents.drain()
        await runtime.aclose()
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
    elif command in {"/new", "/stop"}:
        reply = await runtime.commands.reply(
            InboundEnvelope("cli", _CONVERSATION_ID, command)
        )
        if reply is not None:
            stream.write(f"{reply}\n")
            stream.flush()
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
        outcome = await _curate_once(settings, provider)
    finally:
        await provider.aclose()
    _report_curation(outcome, stream)


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


def _telegram_connector(
    settings: Settings, *, stderr: TextIO | None
) -> TelegramConnector | None:
    """Build the configured chat channel, if one is enabled."""
    channel = settings.channels.telegram
    if not channel.enabled:
        return None
    return TelegramConnector(
        token=channel.token,
        api_base=channel.api_base,
        allowed_chat_ids=channel.allowed_chat_ids,
        poll_timeout_seconds=channel.poll_timeout_seconds,
        stderr=sys.stderr if stderr is None else stderr,
    )


async def run_serve(
    settings: Settings,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    provider_factory: ProviderFactory = build_provider,
) -> int:
    """Run the long-lived host: registered maintenance until shutdown."""
    stream = sys.stdout if stdout is None else stdout
    runtime = await build_runtime(
        settings, provider_factory=provider_factory, stdout=stdout, stderr=stderr
    )
    workbench = WorkbenchServer(
        port=settings.server.port,
        access=AccessPolicy(settings.server.token),
        submit=runtime.hub.submit,
    )
    runtime.hub.register_transport(workbench)
    runtime.hub.subscribe(workbench)
    scheduler = Scheduler()
    interval = settings.schedule.curation_interval_seconds
    if interval is not None:
        scheduler.every(interval, _curation_job(settings, runtime.provider, stream))
    for turn in settings.schedule.turns:
        scheduler.every(
            turn.every_seconds,
            _turn_job(runtime, workbench.transport_id, turn, stderr=stderr),
        )
    if settings.triggers.items:
        consumer = TriggerConsumer(
            build_trigger_queue(settings),
            transport=workbench.transport_id,
            submit=runtime.hub.submit,
        )
        scheduler.every(settings.triggers.poll_interval_seconds, _trigger_job(consumer))
    if settings.heartbeat.enabled:
        scheduler.every(
            settings.heartbeat.interval_seconds,
            _heartbeat_job(runtime, workbench.transport_id, settings, stderr=stderr),
        )
    scheduler.every(
        _CRON_POLL_SECONDS,
        _cron_job(CronRunner(runtime.jobs, submit=runtime.hub.submit, stderr=stderr)),
    )
    connector = _telegram_connector(settings, stderr=stderr)
    connector_task: asyncio.Task[None] | None = None
    if connector is not None:
        runtime.hub.register_transport(connector)
        connector_task = asyncio.create_task(connector.run(runtime.hub.submit))
    workbench.start(asyncio.get_running_loop())
    stream.write("serving\n")
    stream.write(f"health {workbench.url}\n")
    stream.flush()
    try:
        await scheduler.run()
    finally:
        if connector_task is not None:
            connector_task.cancel()
        await asyncio.to_thread(workbench.stop)
        if connector is not None:
            await connector.aclose()
        await runtime.aclose()
        if connector_task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await connector_task
    return 0


async def _curate_once(settings: Settings, provider: ProviderPort) -> CurationOutcome:
    """Apply one curation pass with an already-open provider."""
    layout = MemoryLayout(resolve_workspace_root(settings))
    curator = Curator(
        layout=layout,
        journal=JsonlJournal(layout.journal),
        cursors=JsonCursors(layout.cursors),
        versioning=FsVault(vault_dir(settings), layout.workspace_root),
        redactor=Redactor(configured_secrets(settings)),
        interpreter=ProviderCurator(provider, model=settings.agent.model),
    )
    return await curator.run()


def _report_curation(outcome: CurationOutcome, stream: TextIO) -> None:
    if outcome.changed:
        stream.write(f"curated {', '.join(outcome.changed)}\n")
        if outcome.change_set is not None:
            stream.write(f"change-set {outcome.change_set}\n")
    else:
        stream.write("nothing to curate\n")


def _curation_job(settings: Settings, provider: ProviderPort, stream: TextIO) -> Job:
    """Build the scheduled job that curates memory without killing the host."""

    async def job() -> None:
        try:
            outcome = await _curate_once(settings, provider)
        except NewbotError as exc:
            stream.write(f"warning: scheduled curation failed: {exc}\n")
            stream.flush()
            return
        _report_curation(outcome, stream)
        stream.flush()

    return job


def _turn_job(
    runtime: Runtime, transport: str, turn: ScheduledTurn, *, stderr: TextIO | None
) -> Job:
    """Build the scheduled job that runs one turn in its bound conversation.

    The turn is recorded to its origin session and delivered through the hub to
    the origin transport. A deliberate failure is reported to the operator and
    the next tick still runs.
    """

    async def job() -> None:
        try:
            status = await runtime.hub.submit(
                InboundEnvelope(
                    transport=transport,
                    conversation_id=turn.conversation,
                    text=turn.prompt,
                )
            )
        except NewbotError as exc:
            stream = sys.stderr if stderr is None else stderr
            stream.write(f"warning: scheduled turn failed: {exc}\n")
            stream.flush()
            return
        if status is TurnStatus.FAILED:
            stream = sys.stderr if stderr is None else stderr
            stream.write("warning: scheduled turn failed: turn failed\n")
            stream.flush()

    return job


def _trigger_job(consumer: TriggerConsumer) -> Job:
    """Build the poll job that delivers queued local triggers."""

    async def job() -> None:
        await consumer.consume()

    return job


def _cron_job(runner: CronRunner) -> Job:
    """Build the poll job that dispatches due scheduled jobs."""

    async def job() -> None:
        await runner.dispatch()

    return job


def _heartbeat_job(
    runtime: Runtime, transport: str, settings: Settings, *, stderr: TextIO | None
) -> Job:
    """Build the job that runs workspace heartbeat tasks without notifying anyone.

    The turn is recorded to the heartbeat conversation so a later run can compare
    against it, but nothing is delivered: v1 has no notification gate, so a
    heartbeat stays silent by contract (ADR-019).
    """
    path = resolve_workspace_root(settings) / HEARTBEAT_FILE

    def warn(message: str) -> None:
        stream = sys.stderr if stderr is None else stderr
        stream.write(f"{message}\n")
        stream.flush()

    async def job() -> None:
        try:
            tasks = read_active_tasks(path)
        except (OSError, UnicodeDecodeError) as exc:
            warn(f"warning: heartbeat file unreadable: {exc}")
            return
        if not tasks:
            return
        bullets = "\n".join(f"- {task}" for task in tasks)
        text = f"Heartbeat check. Perform these workspace tasks:\n{bullets}"
        try:
            status = await runtime.hub.submit(
                InboundEnvelope(
                    transport=transport,
                    conversation_id=settings.heartbeat.conversation,
                    text=text,
                    reply=False,
                )
            )
        except NewbotError as exc:
            warn(f"warning: heartbeat turn failed: {exc}")
            return
        if status is TurnStatus.FAILED:
            warn("warning: heartbeat turn failed: turn failed")

    return job


async def run_trigger(
    settings: Settings,
    trigger_id: str,
    text: str,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Queue one local-trigger delivery for the running (or next) host."""
    stream = sys.stdout if stdout is None else stdout
    error = sys.stderr if stderr is None else stderr
    definition = next(
        (item for item in settings.triggers.items if item.id == trigger_id), None
    )
    if definition is None:
        error.write(f"error: unknown trigger {trigger_id!r}\n")
        error.flush()
        return 2
    if not text.strip():
        error.write("error: message must not be empty\n")
        error.flush()
        return 2
    queue = build_trigger_queue(settings)
    try:
        delivery_id = queue.enqueue(trigger_id, definition.conversation, text)
    except TriggerError as exc:
        error.write(f"error: {exc}\n")
        error.flush()
        return 1
    stream.write(f"queued {delivery_id}\n")
    stream.flush()
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
