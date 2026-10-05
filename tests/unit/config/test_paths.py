"""Path helper tests."""

from __future__ import annotations

from pathlib import Path

from newbot.config.paths import config_dir, config_path


def test_env_override_wins(tmp_path: Path) -> None:
    env = {"NEWBOT_CONFIG_DIR": str(tmp_path)}

    assert config_dir(env) == tmp_path
    assert config_path(env) == tmp_path / "config.toml"
