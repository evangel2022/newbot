"""Layered configuration loading with fail-fast, located errors."""

from __future__ import annotations

import os
import re
import tomllib
from collections.abc import Mapping
from pathlib import Path

from pydantic import ValidationError

from newbot.config.paths import config_path
from newbot.config.schema import Settings
from newbot.domain.errors import ConfigLoadError

_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_MAX_REPORTED_ERRORS = 5


def load_settings(
    path: Path | None = None, *, environ: Mapping[str, str] | None = None
) -> Settings:
    """Load, expand, and validate configuration; raise ``ConfigLoadError`` on failure."""
    env = os.environ if environ is None else environ
    resolved_path = path if path is not None else config_path(environ)
    if not resolved_path.is_file():
        raise ConfigLoadError(
            "config file not found; create one or pass --config",
            location=str(resolved_path),
        )
    try:
        text = resolved_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ConfigLoadError(
            "config file must be UTF-8 encoded", location=str(resolved_path)
        ) from exc
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigLoadError(f"invalid TOML: {exc}", location=str(resolved_path)) from exc
    expanded = _expand_env_refs(raw, env, location="")
    try:
        return Settings.model_validate(expanded)
    except ValidationError as exc:
        raise ConfigLoadError(
            _format_validation_error(exc), location=str(resolved_path)
        ) from exc


def _expand_env_refs(value: object, env: Mapping[str, str], *, location: str) -> object:
    if isinstance(value, str):
        match = _ENV_REF.fullmatch(value)
        if match is None:
            return value
        name = match.group(1)
        resolved = env.get(name)
        if resolved is None:
            raise ConfigLoadError(
                f"environment variable {name!r} is not set",
                location=location or "<root>",
            )
        return resolved
    if isinstance(value, dict):
        return {
            str(key): _expand_env_refs(
                child, env, location=f"{location}.{key}" if location else str(key)
            )
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [
            _expand_env_refs(child, env, location=f"{location}[{index}]")
            for index, child in enumerate(value)
        ]
    return value


def _format_validation_error(exc: ValidationError) -> str:
    errors = exc.errors()
    parts = [
        f"{'.'.join(str(item) for item in error['loc']) or '<root>'}: {error['msg']}"
        for error in errors[:_MAX_REPORTED_ERRORS]
    ]
    remaining = len(errors) - _MAX_REPORTED_ERRORS
    if remaining > 0:
        parts.append(f"... and {remaining} more")
    return "; ".join(parts)
