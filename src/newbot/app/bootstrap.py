"""Composition root: build the runtime object graph from resolved settings."""

from __future__ import annotations

import hashlib
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from newbot.adapters.mcp.http import HttpMcpClient
from newbot.adapters.mcp.stdio import StdioMcpClient
from newbot.adapters.providers.registry import ProviderFactory, build_provider
from newbot.adapters.search.duckduckgo import DuckDuckGoSearch
from newbot.adapters.stores.json_jobs import JOBS_DIRNAME, JsonJobStore
from newbot.adapters.stores.json_subagent_tasks import (
    SUBAGENT_TASKS_DIRNAME,
    JsonSubagentTaskStore,
)
from newbot.adapters.stores.jsonl_sessions import JsonlSessionStore
from newbot.adapters.stores.trigger_queue import TriggerQueue
from newbot.adapters.transports.cli import CliTransport
from newbot.app.commands import CommandRouter
from newbot.config.paths import config_dir
from newbot.config.schema import Settings
from newbot.core.context import ContextAssembler
from newbot.core.delegation import SubagentManager
from newbot.core.hub import EventHub
from newbot.core.reasoning import ReasoningLoop
from newbot.core.turn import TurnEngine
from newbot.domain.agent import AgentDefinition
from newbot.domain.errors import NewbotError
from newbot.domain.mcp import McpHttpServerSpec, McpStdioServerSpec
from newbot.domain.plugin import Plugin
from newbot.domain.skill import Skill
from newbot.domain.turn import Budget
from newbot.extensions.discovery import discover_tools
from newbot.extensions.plugins import (
    RESERVED_PLUGIN_ENV,
    discover_plugins,
    merge_mcp_servers,
    merge_skills,
)
from newbot.extensions.skills import load_skills, render_skill_summary
from newbot.policy.network import NetworkGuard
from newbot.policy.redaction import Redactor
from newbot.policy.sandbox import build_sandbox
from newbot.policy.workspace import WorkspaceGuard
from newbot.ports.mcp import McpClientPort
from newbot.ports.provider import ProviderPort
from newbot.session.manager import SessionManager
from newbot.tools.mcp import McpTool
from newbot.tools.registry import build_default_registry
from newbot.tools.web_search import WebSearchTool


@dataclass(frozen=True, slots=True)
class Runtime:
    """The wired object graph for one process."""

    hub: EventHub
    engine: TurnEngine
    provider: ProviderPort
    transport: CliTransport
    sessions: SessionManager
    jobs: JsonJobStore
    mcp: tuple[McpClientPort, ...]
    subagents: SubagentManager
    commands: CommandRouter

    async def aclose(self) -> None:
        """Stop subagents and MCP servers, then close the provider."""
        await self.subagents.shutdown()
        for client in self.mcp:
            await client.aclose()
        await self.provider.aclose()


async def build_runtime(
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
    jobs = JsonJobStore(workspace_root / JOBS_DIRNAME)
    plugins = discover_plugins(
        workspace_root,
        enabled=settings.plugins.enabled,
        data_root=config_dir() / "plugin-data",
    )
    skills = _skills(settings, workspace_root, plugins)
    discovered_tools = tuple(item.tool for item in discover_tools())
    sandbox = build_sandbox(settings.tools.sandbox)
    if sandbox.notice is not None:
        notice_stream = sys.stderr if stderr is None else stderr
        notice_stream.write(f"warning: {sandbox.notice}\n")
    mcp_servers = merge_mcp_servers(_config_mcp_servers(settings), plugins)
    mcp_clients, mcp_tools = await _connect_mcp(
        mcp_servers, ssrf_whitelist=settings.tools.ssrf_whitelist
    )
    network_guard = NetworkGuard(allowed_cidrs=settings.tools.ssrf_whitelist)
    web = settings.tools.web
    web_search = (
        WebSearchTool(
            DuckDuckGoSearch(network_guard),
            default_max_results=web.search.max_results,
        )
        if web.enable
        else None
    )
    subagents = SubagentManager(
        sessions=sessions,
        budget=Budget(max_iterations=settings.agent.max_iterations),
        hub=hub,
        store=JsonSubagentTaskStore(workspace_root / SUBAGENT_TASKS_DIRNAME),
        max_concurrent=settings.agent.max_concurrent_turns,
    )
    try:
        registry = build_default_registry(
            WorkspaceGuard(
                workspace_root,
                read_roots=settings.tools.extra_read_dirs,
                write_roots=settings.tools.extra_write_dirs,
                write_files=settings.tools.extra_write_files,
            ),
            network_guard=network_guard,
            sandbox=sandbox.backend,
            enable_web=web.enable,
            allowlist=settings.agent.tools,
            shell_timeout_seconds=settings.tools.shell_timeout_seconds,
            redactor=Redactor(configured_secrets(settings, plugins)),
            jobs=jobs,
            mcp_tools=mcp_tools,
            web_search=web_search,
            discovered_tools=discovered_tools,
            skills=skills,
            self_state=_self_state(settings, plugins),
            subagents=subagents,
        )
        agent = AgentDefinition(
            model=settings.agent.model,
            system_prompt=_system_prompt(settings.agent.system_prompt, skills),
            budget=Budget(max_iterations=settings.agent.max_iterations),
        )
        reasoning = ReasoningLoop(provider, registry)
        assembler = ContextAssembler(agent, registry)
        subagents.bind(reasoning=reasoning, assembler=assembler)
        engine = TurnEngine(
            hub=hub,
            reasoning=reasoning,
            assembler=assembler,
            agent=agent,
            workspace_root=workspace_root,
            sessions=sessions,
            max_concurrent_turns=settings.agent.max_concurrent_turns,
        )
        transport = CliTransport(stdout=stdout, stderr=stderr)
        router = CommandRouter(
            engine=engine, hub=hub, subagents=subagents, sessions=sessions
        )
        hub.bind_inbound(router.handle)
        hub.register_transport(transport)
        hub.subscribe(transport)
    except NewbotError:
        for client in mcp_clients:
            await client.aclose()
        raise
    return Runtime(
        hub=hub,
        engine=engine,
        provider=provider,
        transport=transport,
        sessions=sessions,
        jobs=jobs,
        mcp=mcp_clients,
        subagents=subagents,
        commands=router,
    )


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
    return SessionManager(
        JsonlSessionStore(sessions_root(settings)),
        workspace_id=_workspace_id(resolve_workspace_root(settings)),
        history_limit=settings.sessions.history_limit,
    )


def sessions_root(settings: Settings) -> Path:
    """Directory holding session JSONL files for this process."""
    return settings.sessions.dir or (config_dir() / "sessions")


def build_trigger_queue(settings: Settings) -> TriggerQueue:
    """Build the durable trigger queue for the configured host."""
    root = settings.triggers.dir or (config_dir() / "triggers")
    return TriggerQueue(root)


def _config_mcp_servers(
    settings: Settings,
) -> dict[str, McpStdioServerSpec | McpHttpServerSpec]:
    """The MCP servers declared in config, as composition-root-ready specs."""
    servers: dict[str, McpStdioServerSpec | McpHttpServerSpec] = {}
    for name, server in settings.tools.mcp.servers.items():
        if server.url:
            servers[name] = McpHttpServerSpec(name=name, url=server.url)
        else:
            servers[name] = McpStdioServerSpec(
                name=name,
                command=server.command,
                args=tuple(server.args),
                env=dict(server.env),
            )
    return servers


async def _connect_mcp(
    servers: Mapping[str, McpStdioServerSpec | McpHttpServerSpec],
    *,
    ssrf_whitelist: Sequence[str],
) -> tuple[tuple[McpClientPort, ...], tuple[McpTool, ...]]:
    """Start every MCP server and adapt its advertised tools.

    A server that cannot start, or that answers the handshake with a protocol
    error, fails the whole startup: a server that silently vanished would hide
    the misconfiguration from the operator.
    """
    guard = NetworkGuard(allowed_cidrs=ssrf_whitelist)
    clients: list[McpClientPort] = []
    tools: list[McpTool] = []
    try:
        for server in servers.values():
            client: McpClientPort
            if isinstance(server, McpHttpServerSpec):
                client = HttpMcpClient(server, guard)
            else:
                client = StdioMcpClient(server)
            await client.start()
            clients.append(client)
            tools.extend(McpTool(client, tool) for tool in await client.list_tools())
    except NewbotError:
        for client in clients:
            await client.aclose()
        raise
    return tuple(clients), tuple(tools)


def configured_secrets(
    settings: Settings, plugins: Sequence[Plugin] = ()
) -> tuple[str, ...]:
    """Runtime secret values that must never reach model context or storage (S6)."""
    candidates: list[str | None] = [
        settings.provider.api_key,
        settings.channels.telegram.token,
    ]
    for server in settings.tools.mcp.servers.values():
        candidates.extend(server.env.values())
    for plugin in plugins:
        for bundled in plugin.mcp_servers:
            if isinstance(bundled, McpStdioServerSpec):
                candidates.extend(
                    value
                    for key, value in bundled.env.items()
                    if key not in RESERVED_PLUGIN_ENV
                )
    return tuple(dict.fromkeys(value for value in candidates if value))


def _skills(
    settings: Settings, workspace_root: Path, plugins: Sequence[Plugin]
) -> tuple[Skill, ...]:
    """Load workspace and plugin skills unless the allowlist drops ``skill``."""
    allowlist = settings.agent.tools
    if allowlist is not None and "skill" not in allowlist:
        return ()
    return merge_skills(load_skills(workspace_root), plugins)


def _self_state(
    settings: Settings, plugins: Sequence[Plugin] = ()
) -> dict[str, object]:
    """Non-secret runtime facts the ``my`` tool may report."""
    allowlist = settings.agent.tools
    bundled = [server.name for plugin in plugins for server in plugin.mcp_servers]
    return {
        "model": settings.agent.model,
        "provider": settings.provider.name,
        "max_iterations": settings.agent.max_iterations,
        "sandbox": settings.tools.sandbox,
        "shell_timeout_seconds": settings.tools.shell_timeout_seconds,
        "allowed_tools": list(allowlist) if allowlist is not None else None,
        "mcp_servers": sorted({*settings.tools.mcp.servers, *bundled}),
        "plugins": sorted(settings.plugins.enabled),
        "web_search": settings.tools.web.enable,
    }


def _system_prompt(base: str, skills: Sequence[Skill]) -> str:
    """Append the skill catalog so the model knows what it can load."""
    summary = render_skill_summary(skills)
    if not summary:
        return base
    return f"{base}\n\n{summary}"
