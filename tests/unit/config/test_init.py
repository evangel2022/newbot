"""Tests for creating default configuration (init)."""

from __future__ import annotations

from pathlib import Path

from newbot.config.init import InitOutcome, initialize
from newbot.config.loader import load_settings


def test_initialize_creates_a_valid_utf8_config_and_workspace(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    workspace = tmp_path / "workspace"

    outcome = initialize(config_file, workspace)

    assert outcome is InitOutcome.CREATED
    assert workspace.is_dir()
    raw = config_file.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" not in raw
    settings = load_settings(config_file, environ={"NEWBOT_API_KEY": "k"})
    assert settings.agent.workspace == workspace


def test_initialize_leaves_an_existing_config_untouched(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text("sentinel", encoding="utf-8")

    outcome = initialize(config_file, tmp_path / "workspace")

    assert outcome is InitOutcome.EXISTS
    assert config_file.read_text(encoding="utf-8") == "sentinel"
