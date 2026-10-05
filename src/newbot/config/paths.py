"""Filesystem path helpers for configuration and runtime data."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path

CONFIG_DIR_ENV = "NEWBOT_CONFIG_DIR"


def config_dir(environ: Mapping[str, str] | None = None) -> Path:
    """Return the config directory, honoring ``NEWBOT_CONFIG_DIR``."""
    env = os.environ if environ is None else environ
    override = env.get(CONFIG_DIR_ENV)
    if override:
        return Path(override)
    if sys.platform == "win32":
        appdata = env.get("APPDATA")
        if appdata:
            return Path(appdata) / "newbot"
        return Path.home() / "AppData" / "Roaming" / "newbot"
    xdg = env.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "newbot"
    return Path.home() / ".config" / "newbot"


def config_path(environ: Mapping[str, str] | None = None) -> Path:
    """Return the default config file path."""
    return config_dir(environ) / "config.toml"
