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


def test_missing_embedded_env_reference_is_located(tmp_path: Path) -> None:
    text = VALID.replace('"${NEWBOT_TEST_KEY}"', '"Bearer ${NEWBOT_TEST_KEY}"')

    with pytest.raises(ConfigLoadError) as info:
        load_settings(_write(tmp_path, text), environ={})

    assert info.value.location == "provider.apiKey"
    assert "NEWBOT_TEST_KEY" in str(info.value)


def test_malformed_env_reference_is_located(tmp_path: Path) -> None:
    text = VALID.replace('"${NEWBOT_TEST_KEY}"', '"${1BAD}"')

    with pytest.raises(ConfigLoadError) as info:
        load_settings(_write(tmp_path, text), environ={"1BAD": "x"})

    assert info.value.location == "provider.apiKey"
    assert "invalid environment reference" in str(info.value)


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


def test_schedule_turns_are_parsed(tmp_path: Path) -> None:
    text = VALID + (
        "\n[[schedule.turns]]\n"
        "everySeconds = 60\n"
        'conversation = "ops"\n'
        'prompt = "do the thing"\n'
    )

    settings = load_settings(_write(tmp_path, text), environ={"NEWBOT_TEST_KEY": "x"})

    assert len(settings.schedule.turns) == 1
    turn = settings.schedule.turns[0]
    assert turn.every_seconds == 60
    assert turn.conversation == "ops"
    assert turn.prompt == "do the thing"


def test_snake_case_schedule_turn_defaults_its_conversation(tmp_path: Path) -> None:
    text = VALID + '\n[[schedule.turns]]\nevery_seconds = 1\nprompt = "ping"\n'

    settings = load_settings(_write(tmp_path, text), environ={"NEWBOT_TEST_KEY": "x"})

    assert settings.schedule.turns[0].conversation == "default"
    assert settings.schedule.turns[0].prompt == "ping"


def test_max_concurrent_turns_is_parsed(tmp_path: Path) -> None:
    text = VALID.replace(
        'model = "gpt-test"', 'model = "gpt-test"\nmaxConcurrentTurns = 2'
    )

    settings = load_settings(_write(tmp_path, text), environ={"NEWBOT_TEST_KEY": "x"})

    assert settings.agent.max_concurrent_turns == 2


def test_max_concurrent_turns_defaults_to_unlimited(tmp_path: Path) -> None:
    settings = load_settings(_write(tmp_path, VALID), environ={"NEWBOT_TEST_KEY": "x"})

    assert settings.agent.max_concurrent_turns is None


def test_invalid_max_concurrent_turns_is_located(tmp_path: Path) -> None:
    text = VALID.replace(
        'model = "gpt-test"', 'model = "gpt-test"\nmaxConcurrentTurns = 0'
    )

    with pytest.raises(ConfigLoadError) as info:
        load_settings(_write(tmp_path, text), environ={"NEWBOT_TEST_KEY": "x"})

    assert "agent.maxConcurrentTurns" in str(info.value)


def test_invalid_schedule_turn_is_located(tmp_path: Path) -> None:
    text = VALID + "\n[[schedule.turns]]\neverySeconds = 0\n"

    with pytest.raises(ConfigLoadError) as info:
        load_settings(_write(tmp_path, text), environ={"NEWBOT_TEST_KEY": "x"})

    message = str(info.value)
    assert "schedule.turns.0.everySeconds" in message
    assert "schedule.turns.0.prompt" in message


def test_triggers_section_is_parsed(tmp_path: Path) -> None:
    text = VALID + (
        "\n[triggers]\n"
        "pollIntervalSeconds = 0.5\n"
        "\n[[triggers.items]]\n"
        'id = "ci"\n'
        'conversation = "ops"\n'
        "\n[[triggers.items]]\n"
        'id = "nightly"\n'
    )

    settings = load_settings(_write(tmp_path, text), environ={"NEWBOT_TEST_KEY": "x"})

    assert settings.triggers.poll_interval_seconds == 0.5
    assert [item.id for item in settings.triggers.items] == ["ci", "nightly"]
    assert settings.triggers.items[0].conversation == "ops"
    assert settings.triggers.items[1].conversation == "default"


def test_duplicate_trigger_ids_are_located(tmp_path: Path) -> None:
    text = VALID + (
        "\n[[triggers.items]]\n"
        'id = "ci"\n'
        "\n[[triggers.items]]\n"
        'id = "ci"\n'
    )

    with pytest.raises(ConfigLoadError) as info:
        load_settings(_write(tmp_path, text), environ={"NEWBOT_TEST_KEY": "x"})

    assert "triggers.items" in str(info.value)


def test_invalid_trigger_poll_interval_is_located(tmp_path: Path) -> None:
    text = VALID + "\n[triggers]\npollIntervalSeconds = 0\n"

    with pytest.raises(ConfigLoadError) as info:
        load_settings(_write(tmp_path, text), environ={"NEWBOT_TEST_KEY": "x"})

    assert "triggers.pollIntervalSeconds" in str(info.value)


def test_heartbeat_section_is_parsed(tmp_path: Path) -> None:
    text = VALID + (
        "\n[heartbeat]\n"
        "enabled = true\n"
        "intervalSeconds = 60\n"
        'conversation = "ops"\n'
    )

    settings = load_settings(_write(tmp_path, text), environ={"NEWBOT_TEST_KEY": "x"})

    assert settings.heartbeat.enabled is True
    assert settings.heartbeat.interval_seconds == 60
    assert settings.heartbeat.conversation == "ops"


def test_heartbeat_defaults_are_quiet(tmp_path: Path) -> None:
    settings = load_settings(_write(tmp_path, VALID), environ={"NEWBOT_TEST_KEY": "x"})

    assert settings.heartbeat.enabled is False
    assert settings.heartbeat.interval_seconds == 1800
    assert settings.heartbeat.conversation == "heartbeat"


def test_invalid_heartbeat_interval_is_located(tmp_path: Path) -> None:
    text = VALID + "\n[heartbeat]\nintervalSeconds = 0\n"

    with pytest.raises(ConfigLoadError) as info:
        load_settings(_write(tmp_path, text), environ={"NEWBOT_TEST_KEY": "x"})

    assert "heartbeat.intervalSeconds" in str(info.value)


def test_empty_heartbeat_conversation_is_located(tmp_path: Path) -> None:
    text = VALID + '\n[heartbeat]\nconversation = ""\n'

    with pytest.raises(ConfigLoadError) as info:
        load_settings(_write(tmp_path, text), environ={"NEWBOT_TEST_KEY": "x"})

    assert "heartbeat.conversation" in str(info.value)


def test_telegram_channel_is_parsed(tmp_path: Path) -> None:
    text = VALID + (
        "\n[channels.telegram]\n"
        "enabled = true\n"
        'token = "bot-token"\n'
        "allowedChatIds = [42, -7]\n"
        "pollTimeoutSeconds = 5\n"
    )

    settings = load_settings(_write(tmp_path, text), environ={"NEWBOT_TEST_KEY": "x"})

    channel = settings.channels.telegram
    assert channel.enabled is True
    assert channel.token == "bot-token"
    assert channel.allowed_chat_ids == [42, -7]
    assert channel.poll_timeout_seconds == 5


def test_telegram_channel_defaults_to_disabled(tmp_path: Path) -> None:
    settings = load_settings(_write(tmp_path, VALID), environ={"NEWBOT_TEST_KEY": "x"})

    assert settings.channels.telegram.enabled is False
    assert settings.channels.telegram.api_base == "https://api.telegram.org"
    assert settings.channels.telegram.allowed_chat_ids == []


def test_enabled_telegram_channel_requires_a_token(tmp_path: Path) -> None:
    text = VALID + "\n[channels.telegram]\nenabled = true\n"

    with pytest.raises(ConfigLoadError) as info:
        load_settings(_write(tmp_path, text), environ={"NEWBOT_TEST_KEY": "x"})

    assert "channels.telegram" in str(info.value)


def test_non_http_telegram_api_base_is_rejected(tmp_path: Path) -> None:
    text = VALID + '\n[channels.telegram]\napiBase = "ftp://nope"\n'

    with pytest.raises(ConfigLoadError) as info:
        load_settings(_write(tmp_path, text), environ={"NEWBOT_TEST_KEY": "x"})

    assert "channels.telegram.apiBase" in str(info.value)


def test_invalid_telegram_poll_timeout_is_located(tmp_path: Path) -> None:
    text = VALID + "\n[channels.telegram]\npollTimeoutSeconds = 0\n"

    with pytest.raises(ConfigLoadError) as info:
        load_settings(_write(tmp_path, text), environ={"NEWBOT_TEST_KEY": "x"})

    assert "channels.telegram.pollTimeoutSeconds" in str(info.value)


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


def test_mcp_servers_are_parsed(tmp_path: Path) -> None:
    text = VALID + (
        "\n[tools.mcp.servers.echo]\n"
        'command = "python"\n'
        'args = ["-m", "server"]\n'
        'env = { TOKEN = "s3cret" }\n'
    )

    settings = load_settings(_write(tmp_path, text), environ={"NEWBOT_TEST_KEY": "x"})

    echo = settings.tools.mcp.servers["echo"]
    assert echo.command == "python"
    assert echo.args == ["-m", "server"]
    assert echo.env == {"TOKEN": "s3cret"}


def test_an_invalid_mcp_server_name_is_located(tmp_path: Path) -> None:
    text = VALID + '\n[tools.mcp.servers."bad name"]\ncommand = "python"\n'

    with pytest.raises(ConfigLoadError) as info:
        load_settings(_write(tmp_path, text), environ={"NEWBOT_TEST_KEY": "x"})

    assert "tools.mcp.servers" in str(info.value)


def test_an_mcp_server_requires_exactly_one_transport(tmp_path: Path) -> None:
    text = VALID + '\n[tools.mcp.servers.echo]\nargs = ["-m", "server"]\n'

    with pytest.raises(ConfigLoadError) as info:
        load_settings(_write(tmp_path, text), environ={"NEWBOT_TEST_KEY": "x"})

    assert "tools.mcp.servers.echo" in str(info.value)


def test_an_mcp_server_cannot_set_both_command_and_url(tmp_path: Path) -> None:
    text = VALID + (
        "\n[tools.mcp.servers.echo]\n"
        'command = "python"\n'
        'url = "https://mcp.example.com/mcp"\n'
    )

    with pytest.raises(ConfigLoadError) as info:
        load_settings(_write(tmp_path, text), environ={"NEWBOT_TEST_KEY": "x"})

    assert "tools.mcp.servers.echo" in str(info.value)


def test_an_mcp_http_server_is_parsed(tmp_path: Path) -> None:
    text = (
        VALID + '\n[tools.mcp.servers.remote]\nurl = "https://mcp.example.com/mcp"\n'
    )

    settings = load_settings(_write(tmp_path, text), environ={"NEWBOT_TEST_KEY": "x"})

    remote = settings.tools.mcp.servers["remote"]
    assert remote.url == "https://mcp.example.com/mcp"
    assert remote.command == ""


def test_a_non_http_mcp_url_is_located(tmp_path: Path) -> None:
    text = VALID + '\n[tools.mcp.servers.remote]\nurl = "ftp://nope"\n'

    with pytest.raises(ConfigLoadError) as info:
        load_settings(_write(tmp_path, text), environ={"NEWBOT_TEST_KEY": "x"})

    assert "tools.mcp.servers.remote.url" in str(info.value)


def test_stdio_only_options_are_rejected_on_an_http_server(tmp_path: Path) -> None:
    text = VALID + (
        "\n[tools.mcp.servers.remote]\n"
        'url = "https://mcp.example.com/mcp"\n'
        'args = ["-m", "server"]\n'
    )

    with pytest.raises(ConfigLoadError) as info:
        load_settings(_write(tmp_path, text), environ={"NEWBOT_TEST_KEY": "x"})

    assert "tools.mcp.servers.remote" in str(info.value)
