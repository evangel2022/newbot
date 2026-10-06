# ADR-028: Plugin-Bundled MCP Servers

- Status: Accepted
- Date: 2026-10-06
- Supersedes: none

## Context

ADR-027 introduced Agent Plugin packages and loaded their bundled skills, but deferred the other
half of ADR-008's plugin definition: "package bundling skills and/or MCP servers". The reference
documents that a plugin may add an `mcp.json`, that enabled stdio servers receive contained
`PLUGIN_ROOT` and isolated `PLUGIN_DATA` paths, and that explicit `tools.mcpServers` entries win
collisions. newbot already has the adapters (`McpStdioServerSpec`/`McpHttpServerSpec`, guarded
HTTP via ADR-024) and the composition-root connection lifecycle.

## Decision

Set the `mcp.json` shape and wire plugin servers through the same path as configured ones.

- `mcp.json` is `{"mcpServers": {"<name>": {"command"|"url", "args", "env"}}}`. It validates by
  reusing `McpServerSettings` (absolute http(s) `url`, exactly one transport, `args`/`env` only
  for stdio) plus the server-name pattern. Unknown top-level keys are ignored for forward
  compatibility; an invalid server is a located `PluginError`.
- `Plugin.mcp_servers` carries composition-ready `McpStdioServerSpec`/`McpHttpServerSpec` values,
  so discovery and transport construction stay separate.
- `discover_plugins(..., data_root)` injects `PLUGIN_ROOT` (the plugin root, already checked to
  be contained) and `PLUGIN_DATA` (`<data_root>/<name>`, isolated per plugin) into every bundled
  stdio server, overriding any manifest value so a package cannot spoof either path.
- `merge_mcp_servers(configured, plugins)` puts plugin servers first and then overlays the
  configured map, so explicit `[tools.mcp.servers]` entries win collisions; two plugins that
  bundle the same server name is an error.
- The composition root converts configured servers to specs, merges, and connects the result
  with the existing fail-fast lifecycle. Plugin stdio `env` values join `configured_secrets`
  (the reserved path keys are excluded, because a path is not a secret).

## Consequences

**Positive**

- A plugin package can now ship skills and/or MCP servers, completing ADR-008's plugin contract.
- Containment and precedence are explicit: `PLUGIN_ROOT`/`PLUGIN_DATA` are computed, config wins
  collisions, and ambiguous plugin/plugin collisions fail startup.
- No core or adapter change: plugin servers reuse `StdioMcpClient`/`HttpMcpClient` and the same
  `mcp__<server>__<tool>` surface as configured servers.

**Negative / accepted costs (deliberate differences, B)**

- **B -- the `mcp.json` key shape is newbot's.** The reference names the file but not its schema;
  `mcpServers` matches the wider MCP ecosystem and reuses our config validation.
- **B -- `PLUGIN_DATA` is not created eagerly.** Discovery stays side-effect free and only points
  the env var at the isolated path; a server that writes state creates it on first use.
- **B -- flat server names.** A bundled server keeps its declared name; there is no per-plugin
  namespacing, matching the reference's "configured entries win collisions" rule.

**Deferred (C)**

- `PLUGIN_DATA` directory provisioning, plugin-hosted HTTP headers/OAuth, and the optional plugin
  logo/permission descriptors.

## Alternatives considered

- **Nest under a `servers` key.** Rejected: it would diverge from the ecosystem's `mcpServers`.
- **Namespace bundled servers as `plugin__<name>__<server>`.** Rejected: the reference resolves
  collisions by precedence, not renaming, and flattening keeps the tool surface predictable.
- **Read `mcp.json` in the composition root instead of discovery.** Rejected: it would split
  plugin validation across layers; discovery already owns the package boundary.
- **Create `PLUGIN_DATA` during discovery.** Rejected: ADR-008 requires discovery to be
  side-effect free.
