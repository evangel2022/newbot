"""Discover and validate Agent Plugins (ADR-027, ADR-028).

A plugin is a package under ``<workspace>/plugins/<name>/`` with a
``plugin.json`` manifest, optionally bundling skills (``skills/*/SKILL.md``)
and MCP servers (``mcp.json``).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from pydantic.alias_generators import to_camel

from newbot.config.schema import McpServerSettings
from newbot.domain.errors import PluginError
from newbot.domain.mcp import McpHttpServerSpec, McpStdioServerSpec
from newbot.domain.plugin import Plugin
from newbot.domain.skill import Skill
from newbot.extensions.skills import SKILL_FILENAME, SKILLS_DIRNAME, load_skills

PLUGINS_DIRNAME = "plugins"
MANIFEST_FILENAME = "plugin.json"
MCP_MANIFEST_FILENAME = "mcp.json"
RESERVED_PLUGIN_ENV = frozenset({"PLUGIN_ROOT", "PLUGIN_DATA"})
_MCP_SERVER_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}")


class _Manifest(BaseModel):
    """The ``plugin.json`` fields newbot reads; unknown keys are ignored."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1)


class _McpManifest(BaseModel):
    """The ``mcp.json`` shape: one ``mcpServers`` mapping of MCP servers."""

    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="ignore"
    )

    mcp_servers: dict[str, McpServerSettings] = Field(default_factory=dict)

    @field_validator("mcp_servers")
    @classmethod
    def _validate_names(
        cls, value: dict[str, McpServerSettings]
    ) -> dict[str, McpServerSettings]:
        for name in value:
            if _MCP_SERVER_NAME.fullmatch(name) is None:
                raise ValueError(
                    f"invalid MCP server name {name!r}; "
                    "use letters, digits, '_' or '-'"
                )
        return value


def discover_plugins(
    workspace_root: Path, *, enabled: Sequence[str], data_root: Path
) -> tuple[Plugin, ...]:
    """Load the enabled Agent Plugins in ``enabled`` order.

    A plugin named in config but not installed, a ``plugin.json`` that fails to
    parse or names a different directory, an ``mcp.json`` that fails to parse,
    and a bundled skill that fails to load are loud errors: the operator
    enabled the package deliberately, so a broken install should fail startup
    instead of silently changing the agent's capabilities. A component that
    resolves outside the plugin root is rejected for the same reason.
    """
    base = workspace_root / PLUGINS_DIRNAME
    plugins: list[Plugin] = []
    for name in enabled:
        root = base / name
        manifest_path = root / MANIFEST_FILENAME
        if not manifest_path.is_file():
            raise PluginError(
                f"plugin {name!r} is not installed: no {MANIFEST_FILENAME} "
                f"under {base}"
            )
        if not _is_contained(base, root) or not _is_contained(root, manifest_path):
            raise PluginError(f"plugin {name!r} escapes {base}")
        manifest = _read_manifest(manifest_path)
        if manifest.name != name:
            raise PluginError(
                f"{manifest_path}: manifest name {manifest.name!r} does not "
                f"match directory {name!r}"
            )
        _require_contained_skills(name, root)
        plugins.append(
            Plugin(
                name=name,
                root=root,
                skills=load_skills(root),
                mcp_servers=_bundled_mcp_servers(name, root, data_root),
            )
        )
    return tuple(plugins)


def merge_skills(
    primary: Sequence[Skill], plugins: Sequence[Plugin]
) -> tuple[Skill, ...]:
    """Merge plugin skills under ``primary``, which wins name collisions."""
    merged: dict[str, Skill] = {skill.name: skill for skill in primary}
    primary_names = set(merged)
    for plugin in plugins:
        for skill in plugin.skills:
            if skill.name in primary_names:
                continue
            if skill.name in merged:
                raise PluginError(
                    f"skill {skill.name!r} is bundled by more than one plugin"
                )
            merged[skill.name] = skill
    return tuple(merged[name] for name in sorted(merged))


def merge_mcp_servers(
    configured: Mapping[str, McpStdioServerSpec | McpHttpServerSpec],
    plugins: Sequence[Plugin],
) -> dict[str, McpStdioServerSpec | McpHttpServerSpec]:
    """Combine plugin servers with configured ones; configured entries win."""
    merged: dict[str, McpStdioServerSpec | McpHttpServerSpec] = {}
    for plugin in plugins:
        for server in plugin.mcp_servers:
            if server.name in merged:
                raise PluginError(
                    f"MCP server {server.name!r} is bundled by more than one plugin"
                )
            merged[server.name] = server
    merged.update(configured)
    return merged


def _read_manifest(path: Path) -> _Manifest:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise PluginError(f"{path}: could not read plugin manifest: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PluginError(f"{path}: invalid plugin manifest JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise PluginError(f"{path}: plugin manifest must be a JSON object")
    try:
        return _Manifest.model_validate(data)
    except ValidationError as exc:
        raise PluginError(f"{path}: invalid plugin manifest: {exc}") from exc


def _read_mcp_manifest(path: Path) -> dict[str, McpServerSettings]:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise PluginError(f"{path}: could not read MCP manifest: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PluginError(f"{path}: invalid MCP manifest JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise PluginError(f"{path}: MCP manifest must be a JSON object")
    try:
        return _McpManifest.model_validate(data).mcp_servers
    except ValidationError as exc:
        raise PluginError(f"{path}: invalid MCP manifest: {exc}") from exc


def _bundled_mcp_servers(
    name: str, root: Path, data_root: Path
) -> tuple[McpStdioServerSpec | McpHttpServerSpec, ...]:
    manifest_path = root / MCP_MANIFEST_FILENAME
    if not manifest_path.is_file():
        return ()
    if not _is_contained(root, manifest_path):
        raise PluginError(f"plugin {name!r}: MCP manifest escapes {root}")
    servers: list[McpStdioServerSpec | McpHttpServerSpec] = []
    for server_name, server in _read_mcp_manifest(manifest_path).items():
        if server.url:
            servers.append(McpHttpServerSpec(name=server_name, url=server.url))
            continue
        env = {
            key: value
            for key, value in server.env.items()
            if key not in RESERVED_PLUGIN_ENV
        }
        env["PLUGIN_ROOT"] = str(root)
        env["PLUGIN_DATA"] = str(data_root / name)
        servers.append(
            McpStdioServerSpec(
                name=server_name,
                command=server.command,
                args=tuple(server.args),
                env=env,
            )
        )
    return tuple(servers)


def _is_contained(root: Path, path: Path) -> bool:
    resolved_root = root.resolve()
    resolved = path.resolve()
    return resolved == resolved_root or resolved_root in resolved.parents


def _require_contained_skills(name: str, root: Path) -> None:
    skills_dir = root / SKILLS_DIRNAME
    if not skills_dir.is_dir():
        return
    if not _is_contained(root, skills_dir):
        raise PluginError(f"plugin {name!r}: skills directory escapes {root}")
    for child in sorted(skills_dir.iterdir()):
        if not child.is_dir():
            continue
        skill_file = child / SKILL_FILENAME
        if skill_file.is_file() and not _is_contained(root, skill_file):
            raise PluginError(f"plugin {name!r}: skill {child.name!r} escapes {root}")
