"""Load, resolve, and validation tests for the configuration boundary."""

from __future__ import annotations

from pathlib import Path

import pytest

from newbot.config.loader import load_settings
from newbot.domain.errors import ConfigLoadError

VALID = """
[provider]
name = "openai_compatible"
baseUrl = "https://api.example.com/v1"
apiKey = "${NEWBOT_TEST_KEY}"

[agent]
model = "gpt-test"
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_and_resolves_env_reference(tmp_path: Path) -> None:
    settings = load_settings(_write(tmp_path, VALID), environ={"NEWBOT_TEST_KEY": "s3cret"})

    assert settings.provider.api_key == "s3cret"
    assert settings.provider.base_url == "https://api.example.com/v1"
    assert settings.agent.model == "gpt-test"


def test_snake_case_keys_are_accepted(tmp_path: Path) -> None:
    text = """
[provider]
base_url = "https://api.example.com/v1"

[agent]
model = "gpt-test"
"""
    assert load_settings(_write(tmp_path, text), environ={}).provider.name == "openai_compatible"


def test_negative_schedule_interval_is_rejected(tmp_path: Path) -> None:
    text = """
[provider]
baseUrl = "https://api.example.com/v1"

[agent]
model = "gpt-test"

[schedule]
curationIntervalSeconds = -1
"""

    with pytest.raises(ConfigLoadError):
        load_settings(_write(tmp_path, text), environ={})


def test_out_of_range_server_port_is_rejected(tmp_path: Path) -> None:
    text = """
[provider]
baseUrl = "https://api.example.com/v1"

[agent]
model = "gpt-test"

[server]
port = 70000
"""

    with pytest.raises(ConfigLoadError):
        load_settings(_write(tmp_path, text), environ={})


def test_missing_env_reference_is_located(tmp_path: Path) -> None:
    with pytest.raises(ConfigLoadError) as info:
        load_settings(_write(tmp_path, VALID), environ={})

    assert info.value.location == "provider.apiKey"
    assert "NEWBOT_TEST_KEY" in str(info.value)


def test_absent_config_file_is_located(tmp_path: Path) -> None:
    missing = tmp_path / "missing.toml"

    with pytest.raises(ConfigLoadError) as info:
        load_settings(missing, environ={})

    assert info.value.location == str(missing)


def test_invalid_toml_is_located(tmp_path: Path) -> None:
    with pytest.raises(ConfigLoadError):
        load_settings(_write(tmp_path, "not = = toml"), environ={})


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    text = VALID + '\nunknownThing = 1\n'

    with pytest.raises(ConfigLoadError):
        load_settings(_write(tmp_path, text), environ={"NEWBOT_TEST_KEY": "x"})


def test_non_http_base_url_is_rejected(tmp_path: Path) -> None:
    text = VALID.replace("https://api.example.com/v1", "ftp://nope")

    with pytest.raises(ConfigLoadError) as info:
        load_settings(_write(tmp_path, text), environ={"NEWBOT_TEST_KEY": "x"})

    assert "provider.baseUrl" in str(info.value)


def test_missing_required_field_is_located(tmp_path: Path) -> None:
    text = VALID.replace('model = "gpt-test"', "")

    with pytest.raises(ConfigLoadError) as info:
        load_settings(_write(tmp_path, text), environ={"NEWBOT_TEST_KEY": "x"})

    assert "agent.model" in str(info.value)


def test_tools_section_is_parsed(tmp_path: Path) -> None:
    text = VALID + '\n[tools]\nssrfWhitelist = ["10.0.0.0/8"]\nshellTimeoutSeconds = 5\n'

    settings = load_settings(_write(tmp_path, text), environ={"NEWBOT_TEST_KEY": "x"})

    assert settings.tools.ssrf_whitelist == ["10.0.0.0/8"]
    assert settings.tools.shell_timeout_seconds == 5


def test_invalid_ssrf_whitelist_is_located(tmp_path: Path) -> None:
    text = VALID + '\n[tools]\nssrfWhitelist = ["not-a-cidr"]\n'

    with pytest.raises(ConfigLoadError) as info:
        load_settings(_write(tmp_path, text), environ={"NEWBOT_TEST_KEY": "x"})

    assert "tools.ssrfWhitelist" in str(info.value)


def test_unknown_sandbox_is_located(tmp_path: Path) -> None:
    text = VALID + '\n[tools]\nsandbox = "chroot"\n'

    with pytest.raises(ConfigLoadError) as info:
        load_settings(_write(tmp_path, text), environ={"NEWBOT_TEST_KEY": "x"})

    assert "tools.sandbox" in str(info.value)


def test_relative_extra_root_is_rejected(tmp_path: Path) -> None:
    text = VALID + '\n[tools]\nextraReadDirs = ["relative/dir"]\n'

    with pytest.raises(ConfigLoadError) as info:
        load_settings(_write(tmp_path, text), environ={"NEWBOT_TEST_KEY": "x"})

    assert "tools.extraReadDirs" in str(info.value)


def test_utf8_bom_is_accepted(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(VALID, encoding="utf-8-sig")

    settings = load_settings(path, environ={"NEWBOT_TEST_KEY": "x"})

    assert settings.agent.model == "gpt-test"


def test_non_utf8_config_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_bytes(VALID.encode("utf-16"))

    with pytest.raises(ConfigLoadError) as info:
        load_settings(path, environ={"NEWBOT_TEST_KEY": "x"})

    assert info.value.location == str(path)
    assert "UTF-8" in str(info.value)
