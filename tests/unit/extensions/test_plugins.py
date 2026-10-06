"""Agent Plugin discovery, validation, and skill merging."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from newbot.domain.errors import PluginError, SkillError
from newbot.domain.mcp import McpHttpServerSpec, McpStdioServerSpec
from newbot.domain.plugin import Plugin
from newbot.domain.session import SessionKey
from newbot.domain.skill import Skill
from newbot.domain.tool import ToolCall
from newbot.extensions.plugins import (
    MANIFEST_FILENAME,
    PLUGINS_DIRNAME,
    _is_contained,
    discover_plugins,
    merge_mcp_servers,
    merge_skills,
)
from newbot.policy.network import NetworkGuard
from newbot.policy.workspace import WorkspaceGuard
from newbot.ports.tools import ToolContext
from newbot.tools.registry import build_default_registry


def _write_plugin(
    workspace: Path,
    name: str,
    *,
    manifest: object | None = None,
    manifest_name: str | None = None,
    skills: dict[str, str] | None = None,
) -> Path:
    root = workspace / PLUGINS_DIRNAME / name
    root.mkdir(parents=True)
    payload = {"name": manifest_name or name} if manifest is None else manifest
    (root / MANIFEST_FILENAME).write_text(json.dumps(payload), encoding="utf-8")
    for skill_name, description in (skills or {}).items():
        directory = root / "skills" / skill_name
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text(
            f"---\ndescription: {description}\n---\n\nbody of {skill_name}\n",
            encoding="utf-8",
        )
    return root


def _write_mcp(root: Path, servers: dict[str, object]) -> None:
    (root / "mcp.json").write_text(
        json.dumps({"mcpServers": servers}), encoding="utf-8"
    )


def test_discovers_an_enabled_plugin_and_its_skills(tmp_path: Path) -> None:
    root = _write_plugin(tmp_path, "greeter", skills={"hello": "say hello"})

    plugins = discover_plugins(tmp_path, data_root=tmp_path / "data", enabled=["greeter"])

    assert [plugin.name for plugin in plugins] == ["greeter"]
    assert plugins[0].root == root
    assert [skill.name for skill in plugins[0].skills] == ["hello"]
    assert plugins[0].skills[0].description == "say hello"
    assert plugins[0].skills[0].body == "body of hello"


def test_disabled_plugins_are_never_read(tmp_path: Path) -> None:
    root = tmp_path / PLUGINS_DIRNAME / "broken"
    root.mkdir(parents=True)
    (root / MANIFEST_FILENAME).write_text("{not json", encoding="utf-8")

    assert discover_plugins(tmp_path, data_root=tmp_path / "data", enabled=[]) == ()


def test_plugin_named_in_config_must_be_installed(tmp_path: Path) -> None:
    with pytest.raises(PluginError, match="is not installed"):
        discover_plugins(tmp_path, data_root=tmp_path / "data", enabled=["missing"])


def test_manifest_name_must_match_the_directory(tmp_path: Path) -> None:
    _write_plugin(tmp_path, "greeter", manifest_name="other")

    with pytest.raises(PluginError, match="does not match"):
        discover_plugins(tmp_path, data_root=tmp_path / "data", enabled=["greeter"])


def test_invalid_manifest_json_is_an_error(tmp_path: Path) -> None:
    root = _write_plugin(tmp_path, "greeter")
    (root / MANIFEST_FILENAME).write_text("{not json", encoding="utf-8")

    with pytest.raises(PluginError, match="invalid plugin manifest JSON"):
        discover_plugins(tmp_path, data_root=tmp_path / "data", enabled=["greeter"])


def test_manifest_must_be_a_json_object(tmp_path: Path) -> None:
    _write_plugin(tmp_path, "greeter", manifest=["greeter"])

    with pytest.raises(PluginError, match="must be a JSON object"):
        discover_plugins(tmp_path, data_root=tmp_path / "data", enabled=["greeter"])


def test_manifest_needs_a_name(tmp_path: Path) -> None:
    _write_plugin(tmp_path, "greeter", manifest={})

    with pytest.raises(PluginError, match="invalid plugin manifest"):
        discover_plugins(tmp_path, data_root=tmp_path / "data", enabled=["greeter"])


def test_plugin_without_skills_is_allowed(tmp_path: Path) -> None:
    _write_plugin(tmp_path, "empty")

    plugins = discover_plugins(tmp_path, data_root=tmp_path / "data", enabled=["empty"])

    assert plugins[0].skills == ()


def test_malformed_bundled_skill_fails(tmp_path: Path) -> None:
    root = _write_plugin(tmp_path, "greeter")
    directory = root / "skills" / "broken"
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text("no frontmatter", encoding="utf-8")

    with pytest.raises(SkillError):
        discover_plugins(tmp_path, data_root=tmp_path / "data", enabled=["greeter"])


def test_merge_prefers_the_workspace_skill(tmp_path: Path) -> None:
    workspace = Skill(name="hello", description="workspace", body="from workspace")
    plugin = Plugin(
        name="greeter",
        root=tmp_path,
        skills=(Skill(name="hello", description="plugin", body="from plugin"),),
    )

    merged = merge_skills([workspace], [plugin])

    assert [skill.body for skill in merged] == ["from workspace"]


def test_merge_orders_skills_by_name(tmp_path: Path) -> None:
    plugin = Plugin(
        name="greeter",
        root=tmp_path,
        skills=(Skill(name="alpha", description="a", body="a"),),
    )

    merged = merge_skills([Skill(name="beta", description="b", body="b")], [plugin])

    assert [skill.name for skill in merged] == ["alpha", "beta"]


def test_merge_rejects_two_plugins_with_the_same_skill(tmp_path: Path) -> None:
    first = Plugin(
        name="a", root=tmp_path, skills=(Skill(name="dup", description="a", body="a"),)
    )
    second = Plugin(
        name="b", root=tmp_path, skills=(Skill(name="dup", description="b", body="b"),)
    )

    with pytest.raises(PluginError, match="more than one plugin"):
        merge_skills([], [first, second])


def test_is_contained_detects_an_escaping_path(tmp_path: Path) -> None:
    root = tmp_path / PLUGINS_DIRNAME / "greeter"
    root.mkdir(parents=True)

    assert _is_contained(root, root / "skills" / "hello") is True
    assert _is_contained(root, root / ".." / "elsewhere") is False


async def test_plugin_skill_is_readable_through_the_skill_tool(tmp_path: Path) -> None:
    _write_plugin(tmp_path, "greeter", skills={"hello": "say hello"})
    plugins = discover_plugins(tmp_path, data_root=tmp_path / "data", enabled=["greeter"])
    registry = build_default_registry(
        WorkspaceGuard(tmp_path),
        network_guard=NetworkGuard(),
        skills=merge_skills((), plugins),
    )
    ctx = ToolContext(session=SessionKey("cli", "default"), workspace_root=tmp_path)

    result = await registry.invoke(
        ToolCall(id="c1", name="skill", arguments='{"action":"read","name":"hello"}'),
        ctx,
    )

    assert result.is_error is False
    assert result.content == "body of hello"


def test_bundles_a_stdio_server_with_plugin_paths(tmp_path: Path) -> None:
    root = _write_plugin(tmp_path, "bundle")
    _write_mcp(
        root,
        {"stub": {"command": "python", "args": ["server.py"], "env": {"TOKEN": "s"}}},
    )

    plugin = discover_plugins(
        tmp_path, data_root=tmp_path / "data", enabled=["bundle"]
    )[0]

    assert len(plugin.mcp_servers) == 1
    server = plugin.mcp_servers[0]
    assert isinstance(server, McpStdioServerSpec)
    assert server.name == "stub"
    assert server.command == "python"
    assert server.args == ("server.py",)
    assert server.env["TOKEN"] == "s"
    assert server.env["PLUGIN_ROOT"] == str(root)
    assert server.env["PLUGIN_DATA"] == str(tmp_path / "data" / "bundle")


def test_plugin_env_cannot_override_the_reserved_paths(tmp_path: Path) -> None:
    root = _write_plugin(tmp_path, "bundle")
    _write_mcp(
        root,
        {"stub": {"command": "python", "env": {"PLUGIN_ROOT": "/etc", "PLUGIN_DATA": "/tmp"}}},
    )

    plugin = discover_plugins(
        tmp_path, data_root=tmp_path / "data", enabled=["bundle"]
    )[0]

    server = plugin.mcp_servers[0]
    assert isinstance(server, McpStdioServerSpec)
    assert server.env["PLUGIN_ROOT"] == str(root)
    assert server.env["PLUGIN_DATA"] == str(tmp_path / "data" / "bundle")


def test_bundles_an_http_server(tmp_path: Path) -> None:
    root = _write_plugin(tmp_path, "bundle")
    _write_mcp(root, {"remote": {"url": "https://example.com/mcp"}})

    plugin = discover_plugins(
        tmp_path, data_root=tmp_path / "data", enabled=["bundle"]
    )[0]

    server = plugin.mcp_servers[0]
    assert isinstance(server, McpHttpServerSpec)
    assert server.name == "remote"
    assert server.url == "https://example.com/mcp"


def test_invalid_mcp_manifest_json_is_an_error(tmp_path: Path) -> None:
    root = _write_plugin(tmp_path, "bundle")
    (root / "mcp.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(PluginError, match="invalid MCP manifest JSON"):
        discover_plugins(tmp_path, data_root=tmp_path / "data", enabled=["bundle"])


def test_mcp_manifest_rejects_a_server_with_no_transport(tmp_path: Path) -> None:
    root = _write_plugin(tmp_path, "bundle")
    _write_mcp(root, {"stub": {"args": ["x"]}})

    with pytest.raises(PluginError, match="invalid MCP manifest"):
        discover_plugins(tmp_path, data_root=tmp_path / "data", enabled=["bundle"])


def test_merge_mcp_servers_lets_configured_entries_win(tmp_path: Path) -> None:
    plugin = Plugin(
        name="bundle",
        root=tmp_path,
        skills=(),
        mcp_servers=(McpStdioServerSpec(name="stub", command="from-plugin"),),
    )
    configured = {"stub": McpStdioServerSpec(name="stub", command="from-config")}

    merged = merge_mcp_servers(configured, [plugin])

    assert merged["stub"].command == "from-config"


def test_merge_mcp_servers_rejects_two_plugins_with_the_same_server(
    tmp_path: Path,
) -> None:
    first = Plugin(
        name="a",
        root=tmp_path,
        skills=(),
        mcp_servers=(McpStdioServerSpec(name="dup", command="a"),),
    )
    second = Plugin(
        name="b",
        root=tmp_path,
        skills=(),
        mcp_servers=(McpStdioServerSpec(name="dup", command="b"),),
    )

    with pytest.raises(PluginError, match="more than one plugin"):
        merge_mcp_servers({}, [first, second])
