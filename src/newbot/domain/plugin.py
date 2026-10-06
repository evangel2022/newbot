"""Value types for Agent Plugins (workspace extension packages)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from newbot.domain.mcp import McpHttpServerSpec, McpStdioServerSpec
from newbot.domain.skill import Skill


@dataclass(frozen=True, slots=True)
class Plugin:
    """One enabled plugin package and the components it bundles."""

    name: str
    root: Path
    skills: tuple[Skill, ...]
    mcp_servers: tuple[McpStdioServerSpec | McpHttpServerSpec, ...] = ()
