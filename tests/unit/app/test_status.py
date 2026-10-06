"""The ``status`` renderer reports resolved config without secrets or a model call."""

from __future__ import annotations

from pathlib import Path

from newbot.app.status import render_status
from newbot.config.schema import Settings


def _settings(root: Path) -> Settings:
    return Settings.model_validate(
        {
            "provider": {
                "baseUrl": "https://api.example.com/v1",
                "apiKey": "provider-secret",
            },
            "agent": {
                "model": "gpt-test",
                "workspace": str(root / "ws"),
                "tools": ["read_file", "my"],
            },
            "sessions": {"dir": str(root / "sessions")},
            "heartbeat": {"enabled": True},
            "tools": {
                "sandbox": "bwrap",
                "shellTimeoutSeconds": 12,
                "mcp": {
                    "servers": {
                        "stub": {"command": "python", "env": {"TOKEN": "mcp-secret"}}
                    }
                },
            },
            "channels": {"telegram": {"enabled": True, "token": "tg-secret"}},
        }
    )


def test_status_rows_report_resolved_config(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    config = tmp_path / "config.toml"

    text = render_status(settings, config_path=config)
    lines = text.splitlines()

    assert lines[0] == f"config: {config}"
    assert f"workspace: {(tmp_path / 'ws').resolve()}" in lines
    assert f"sessions: {tmp_path / 'sessions'}" in lines
    assert "provider: openai_compatible" in lines
    assert "base url: https://api.example.com/v1" in lines
    assert "provider key: set" in lines
    assert "model: gpt-test" in lines
    assert "max iterations: 8" in lines
    assert "tools: read_file, my" in lines
    assert "mcp servers: stub" in lines
    assert "sandbox: bwrap" in lines
    assert "shell timeout: 12s" in lines
    assert "heartbeat: enabled" in lines
    assert "telegram: enabled" in lines
    assert text.endswith("\n")


def test_status_reports_defaults_without_a_configured_key(tmp_path: Path) -> None:
    settings = Settings.model_validate(
        {
            "provider": {"baseUrl": "https://api.example.com/v1"},
            "agent": {"model": "gpt-test", "workspace": str(tmp_path / "ws")},
            "sessions": {"dir": str(tmp_path / "sessions")},
        }
    )

    text = render_status(settings, config_path=tmp_path / "config.toml")

    assert "provider key: unset" in text
    assert "tools: all built-ins" in text
    assert "mcp servers: (none)" in text
    assert "sandbox: none" in text
    assert "heartbeat: disabled" in text
    assert "telegram: disabled" in text


def test_status_never_prints_secret_values(tmp_path: Path) -> None:
    text = render_status(_settings(tmp_path), config_path=tmp_path / "config.toml")

    assert "provider-secret" not in text
    assert "mcp-secret" not in text
    assert "tg-secret" not in text
