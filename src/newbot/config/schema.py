"""Typed configuration schema. Unknown keys are rejected, never coerced."""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

DEFAULT_SYSTEM_PROMPT = "You are newbot, a concise and helpful AI agent."
_MCP_SERVER_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}")
_PLUGIN_NAME = re.compile(r"[A-Za-z0-9._-]{1,64}")


class _SettingsModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid"
    )


def _require_http_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("must be an absolute http(s) URL")
    return value


class ProviderSettings(_SettingsModel):
    """Settings for the selected provider backend."""

    name: str = "openai_compatible"
    base_url: str
    api_key: str | None = None
    max_tokens: int | None = Field(default=None, gt=0)

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, value: str) -> str:
        return _require_http_url(value)


class AgentSettings(_SettingsModel):
    """The model-facing identity of the agent."""

    model: str
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    workspace: Path | None = None
    tools: list[str] | None = None
    max_iterations: int = Field(default=8, gt=0)
    max_concurrent_turns: int | None = Field(default=None, gt=0)


class SessionSettings(_SettingsModel):
    """Session persistence settings."""

    dir: Path | None = None
    history_limit: int = Field(default=40, gt=0)


class ScheduledTurn(_SettingsModel):
    """One recurring agent turn bound to a conversation on the host transport."""

    every_seconds: float = Field(gt=0)
    conversation: str = Field(default="default", min_length=1)
    prompt: str = Field(min_length=1)


class ScheduleSettings(_SettingsModel):
    """Timed work for the long-running host."""

    curation_interval_seconds: float | None = Field(default=None, gt=0)
    turns: list[ScheduledTurn] = Field(default_factory=list)


class TriggerDefinition(_SettingsModel):
    """One named local trigger bound to a conversation on the host transport."""

    id: str = Field(min_length=1)
    conversation: str = Field(default="default", min_length=1)


class TriggerSettings(_SettingsModel):
    """Durable local trigger deliveries for the long-running host."""

    dir: Path | None = None
    poll_interval_seconds: float = Field(default=1.0, gt=0)
    items: list[TriggerDefinition] = Field(default_factory=list)

    @field_validator("items")
    @classmethod
    def _unique_ids(cls, value: list[TriggerDefinition]) -> list[TriggerDefinition]:
        seen: set[str] = set()
        for item in value:
            if item.id in seen:
                raise ValueError(f"duplicate trigger id {item.id!r}")
            seen.add(item.id)
        return value


class HeartbeatSettings(_SettingsModel):
    """Protected recurring workspace checks that normally stay quiet."""

    enabled: bool = False
    interval_seconds: float = Field(default=1800.0, gt=0)
    conversation: str = Field(default="heartbeat", min_length=1)


class ServerSettings(_SettingsModel):
    """The loopback HTTP surface of the long-running host."""

    port: int = Field(default=8787, ge=0, le=65535)
    token: str | None = None


class McpServerSettings(_SettingsModel):
    """One Model Context Protocol server the agent can launch or reach."""

    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str = ""

    @field_validator("url")
    @classmethod
    def _validate_url(cls, value: str) -> str:
        return _require_http_url(value) if value else value

    @model_validator(mode="after")
    def _require_one_transport(self) -> McpServerSettings:
        if bool(self.command) == bool(self.url):
            raise ValueError("configure exactly one of 'command' or 'url'")
        if self.url and (self.args or self.env):
            raise ValueError("'args' and 'env' only apply to a stdio server")
        return self


class McpSettings(_SettingsModel):
    """MCP servers, keyed by the name tools are namespaced under."""

    servers: dict[str, McpServerSettings] = Field(default_factory=dict)

    @field_validator("servers")
    @classmethod
    def _validate_server_names(
        cls, value: dict[str, McpServerSettings]
    ) -> dict[str, McpServerSettings]:
        for name in value:
            if _MCP_SERVER_NAME.fullmatch(name) is None:
                raise ValueError(
                    f"invalid MCP server name {name!r}; "
                    "use letters, digits, '_' or '-'"
                )
        return value


class WebSearchSettings(_SettingsModel):
    """The selected web search provider and its result bound."""

    provider: str = "duckduckgo"
    max_results: int = Field(default=5, gt=0, le=20)

    @field_validator("provider")
    @classmethod
    def _validate_provider(cls, value: str) -> str:
        if value != "duckduckgo":
            raise ValueError(f"unsupported web search provider {value!r}")
        return value


class WebSettings(_SettingsModel):
    """Built-in web tools (fetch and search)."""

    enable: bool = True
    search: WebSearchSettings = Field(default_factory=WebSearchSettings)


class ToolsSettings(_SettingsModel):
    """Tool capability policy."""

    sandbox: str = "none"
    ssrf_whitelist: list[str] = Field(default_factory=list)
    shell_timeout_seconds: float = Field(default=30.0, gt=0)
    extra_read_dirs: list[Path] = Field(default_factory=list)
    extra_write_dirs: list[Path] = Field(default_factory=list)
    extra_write_files: list[Path] = Field(default_factory=list)
    mcp: McpSettings = Field(default_factory=McpSettings)
    web: WebSettings = Field(default_factory=WebSettings)

    @field_validator("sandbox")
    @classmethod
    def _validate_sandbox(cls, value: str) -> str:
        if value not in {"none", "bwrap", "seatbelt"}:
            raise ValueError(f"unknown sandbox {value!r}")
        return value

    @field_validator("extra_read_dirs", "extra_write_dirs", "extra_write_files")
    @classmethod
    def _validate_absolute_paths(cls, value: list[Path]) -> list[Path]:
        for path in value:
            if not path.is_absolute():
                raise ValueError(f"path must be absolute: {path}")
        return value

    @field_validator("ssrf_whitelist")
    @classmethod
    def _validate_ssrf_whitelist(cls, value: list[str]) -> list[str]:
        for entry in value:
            try:
                ipaddress.ip_network(entry, strict=False)
            except ValueError as exc:
                raise ValueError(f"invalid CIDR {entry!r}: {exc}") from exc
        return value


class TelegramSettings(_SettingsModel):
    """One Telegram bot channel."""

    enabled: bool = False
    token: str = ""
    api_base: str = "https://api.telegram.org"
    allowed_chat_ids: list[int] = Field(default_factory=list)
    poll_timeout_seconds: float = Field(default=30.0, gt=0)

    @field_validator("api_base")
    @classmethod
    def _validate_api_base(cls, value: str) -> str:
        return _require_http_url(value)

    @model_validator(mode="after")
    def _require_token_when_enabled(self) -> TelegramSettings:
        if self.enabled and not self.token:
            raise ValueError("token is required when the channel is enabled")
        return self


class ChannelsSettings(_SettingsModel):
    """External chat channels the host can serve."""

    telegram: TelegramSettings = Field(default_factory=TelegramSettings)


class PluginSettings(_SettingsModel):
    """Agent Plugins v1 installed in the workspace and enabled by name."""

    enabled: list[str] = Field(default_factory=list)

    @field_validator("enabled")
    @classmethod
    def _validate_enabled(cls, value: list[str]) -> list[str]:
        seen: set[str] = set()
        for name in value:
            if _PLUGIN_NAME.fullmatch(name) is None:
                raise ValueError(
                    f"invalid plugin name {name!r}; "
                    "use letters, digits, '.', '_' or '-'"
                )
            if name in seen:
                raise ValueError(f"duplicate plugin {name!r}")
            seen.add(name)
        return value


class Settings(_SettingsModel):
    """Fully resolved runtime configuration."""

    provider: ProviderSettings
    agent: AgentSettings
    sessions: SessionSettings = Field(default_factory=SessionSettings)
    schedule: ScheduleSettings = Field(default_factory=ScheduleSettings)
    triggers: TriggerSettings = Field(default_factory=TriggerSettings)
    heartbeat: HeartbeatSettings = Field(default_factory=HeartbeatSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)
    tools: ToolsSettings = Field(default_factory=ToolsSettings)
    channels: ChannelsSettings = Field(default_factory=ChannelsSettings)
    plugins: PluginSettings = Field(default_factory=PluginSettings)
