"""Composition root: build the runtime object graph from resolved settings."""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from newbot.adapters.providers.registry import ProviderFactory, build_provider
from newbot.adapters.stores.jsonl_sessions import JsonlSessionStore
from newbot.adapters.transports.cli import CliTransport
from newbot.config.paths import config_dir
from newbot.config.schema import Settings
from newbot.core.context import ContextAssembler
from newbot.core.hub import EventHub
from newbot.core.reasoning import ReasoningLoop
from newbot.core.turn import TurnEngine
from newbot.domain.agent import AgentDefinition
from newbot.domain.turn import Budget
from newbot.policy.network import NetworkGuard
from newbot.policy.redaction import Redactor
from newbot.policy.sandbox import build_sandbox
from newbot.policy.workspace import WorkspaceGuard
from newbot.ports.provider import ProviderPort
from newbot.session.manager import SessionManager
from newbot.tools.registry import build_default_registry


@dataclass(frozen=True, slots=True)
class Runtime:
    """The wired object graph for one process."""

    hub: EventHub
    engine: TurnEngine
    provider: ProviderPort
    transport: CliTransport


def build_runtime(
    settings: Settings,
    *,
    provider_factory: ProviderFactory = build_provider,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> Runtime:
    """Construct the provider, core, hub, and transport, then wire them."""
    provider = provider_factory(settings.provider)
    hub = EventHub()
    workspace_root = resolve_workspace_root(settings)
    sessions = build_sessions(settings)
    sandbox = build_sandbox(settings.tools.sandbox)
    if sandbox.notice is not None:
        notice_stream = sys.stderr if stderr is None else stderr
        notice_stream.write(f"warning: {sandbox.notice}\n")
    registry = build_default_registry(
        WorkspaceGuard(
            workspace_root,
            read_roots=settings.tools.extra_read_dirs,
            write_roots=settings.tools.extra_write_dirs,
            write_files=settings.tools.extra_write_files,
        ),
        network_guard=NetworkGuard(allowed_cidrs=settings.tools.ssrf_whitelist),
        sandbox=sandbox.backend,
        allowlist=settings.agent.tools,
        shell_timeout_seconds=settings.tools.shell_timeout_seconds,
        redactor=Redactor(configured_secrets(settings)),
    )
    agent = AgentDefinition(
        model=settings.agent.model,
        system_prompt=settings.agent.system_prompt,
        budget=Budget(max_iterations=settings.agent.max_iterations),
    )
    engine = TurnEngine(
        hub=hub,
        reasoning=ReasoningLoop(provider, registry),
        assembler=ContextAssembler(agent, registry),
        agent=agent,
        workspace_root=workspace_root,
        sessions=sessions,
    )
    transport = CliTransport(stdout=stdout, stderr=stderr)
    hub.bind_inbound(engine.handle)
    hub.register_transport(transport)
    hub.subscribe(transport)
    return Runtime(hub=hub, engine=engine, provider=provider, transport=transport)


def _workspace_id(root: Path) -> str:
    return hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:16]


def resolve_workspace_root(settings: Settings) -> Path:
    """Resolve the agent workspace root for one process."""
    return (settings.agent.workspace or Path.cwd()).resolve()


def vault_dir(settings: Settings) -> Path:
    """Directory holding durable-file versions for this workspace."""
    return config_dir() / "vault" / _workspace_id(resolve_workspace_root(settings))


def build_sessions(settings: Settings) -> SessionManager:
    """Build the persistent session manager for the CLI conversation."""
    sessions_root = settings.sessions.dir or (config_dir() / "sessions")
    return SessionManager(
        JsonlSessionStore(sessions_root),
        workspace_id=_workspace_id(resolve_workspace_root(settings)),
        history_limit=settings.sessions.history_limit,
    )


def configured_secrets(settings: Settings) -> tuple[str, ...]:
    """Runtime secret values that must never reach model context or storage (S6)."""
    api_key = settings.provider.api_key
    return (api_key,) if api_key else ()
