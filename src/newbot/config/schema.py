"""Typed configuration schema. Unknown keys are rejected, never coerced."""

from __future__ import annotations

import ipaddress
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

DEFAULT_SYSTEM_PROMPT = "You are newbot, a concise and helpful AI agent."


class _SettingsModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid"
    )


class ProviderSettings(_SettingsModel):
    """Settings for the selected provider backend."""

    name: str = "openai_compatible"
    base_url: str
    api_key: str | None = None
    max_tokens: int | None = Field(default=None, gt=0)

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ValueError("base_url must be an absolute http(s) URL")
        return value


class AgentSettings(_SettingsModel):
    """The model-facing identity of the agent."""

    model: str
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    workspace: Path | None = None
    tools: list[str] | None = None
    max_iterations: int = Field(default=8, gt=0)


class SessionSettings(_SettingsModel):
    """Session persistence settings."""

    dir: Path | None = None
    history_limit: int = Field(default=40, gt=0)


class ToolsSettings(_SettingsModel):
    """Tool capability policy."""

    sandbox: str = "none"
    ssrf_whitelist: list[str] = Field(default_factory=list)
    shell_timeout_seconds: float = Field(default=30.0, gt=0)
    extra_read_dirs: list[Path] = Field(default_factory=list)
    extra_write_dirs: list[Path] = Field(default_factory=list)
    extra_write_files: list[Path] = Field(default_factory=list)

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


class Settings(_SettingsModel):
    """Fully resolved runtime configuration."""

    provider: ProviderSettings
    agent: AgentSettings
    sessions: SessionSettings = Field(default_factory=SessionSettings)
    tools: ToolsSettings = Field(default_factory=ToolsSettings)
