"""Config-only health summary for the ``status`` command."""

from __future__ import annotations

from pathlib import Path

from newbot.app.bootstrap import resolve_workspace_root, sessions_root
from newbot.config.schema import Settings


def render_status(settings: Settings, *, config_path: Path) -> str:
    """Render resolved configuration; never constructs a provider or calls a model."""
    rows: list[tuple[str, str]] = [
        ("config", str(config_path)),
        ("workspace", str(resolve_workspace_root(settings))),
        ("sessions", str(sessions_root(settings))),
        ("provider", settings.provider.name),
        ("base url", settings.provider.base_url),
        ("provider key", _present(settings.provider.api_key)),
        ("model", settings.agent.model),
        ("max iterations", str(settings.agent.max_iterations)),
        ("tools", _tools(settings.agent.tools)),
        ("mcp servers", _listed(sorted(settings.tools.mcp.servers))),
        ("sandbox", settings.tools.sandbox),
        ("shell timeout", f"{settings.tools.shell_timeout_seconds:g}s"),
        ("heartbeat", _flag(settings.heartbeat.enabled)),
        ("telegram", _flag(settings.channels.telegram.enabled)),
        ("plugins", _listed(sorted(settings.plugins.enabled))),
    ]
    return "".join(f"{label}: {value}\n" for label, value in rows)


def _present(value: str | None) -> str:
    return "set" if value else "unset"


def _flag(value: bool) -> str:
    return "enabled" if value else "disabled"


def _tools(allowlist: list[str] | None) -> str:
    if allowlist is None:
        return "all built-ins"
    return _listed(allowlist)


def _listed(names: list[str]) -> str:
    return ", ".join(names) if names else "(none)"
