# ADR-022: Model Context Protocol Tools (stdio)

- Status: Accepted
- Date: 2026-10-05
- Supersedes: none

## Context

Phase 5 grows capability at the edge without touching the core. nanobot
(`docs/guides/configure-mcp-tools.md`, `configuration.md`) configures `tools.mcpServers` with stdio
(`command`, `args`, `env`) and HTTP/SSE (`url`) servers, discovers their tools, and exposes them to
the model under an `enabledTools` allowlist; HTTP endpoints pass the SSRF guard, while stdio servers
sit outside the HTTP guard. newbot had no MCP surface, so the behavior matrix records MCP as
**C -- not implemented**.

## Decision

One stdio client and one tool adapter; the composition root owns the lifecycle.

- `domain/mcp.py` adds `McpServerSpec`, `McpToolSpec`, and `McpToolResult`; `ports/mcp.py` defines
  `McpClientPort`. `adapters/mcp/stdio.py` implements it as `StdioMcpClient`: it launches the
  configured command, completes the `initialize`/`notifications/initialized` handshake, and speaks
  newline-delimited JSON-RPC 2.0 over the process pipes. Requests are serialized with a lock, each
  read is bounded by a timeout, and every reply is parsed at the boundary with pydantic, so a
  malformed or errored message is a typed `McpError` rather than a crash. A bounded tail of the
  server's stderr is kept for diagnostics; it never enters model context.
- `tools/mcp.py` adds `McpTool`, one adapter per advertised tool. The model-facing name is
  namespaced `mcp__<server>__<tool>` with unsafe characters replaced, so it cannot collide with a
  built-in; the server-side name is kept verbatim for `tools/call`, and the remote JSON schema is
  passed through unchanged. A result with `isError` becomes an error tool result.
- `config/schema.py` adds `[tools.mcp.servers.<name>]` with `command`, `args`, and `env`. Server
  names are validated (`[A-Za-z0-9_-]{1,64}`) because they are part of the tool name. MCP `env`
  values join `configured_secrets`, so they are redacted from tool output and the journal.
- The composition root connects: `build_runtime` is now async, starts every configured server,
  adapts its tools, and adds them to the default registry (still filtered by `[agent].tools`). A
  server that cannot start, or that fails the handshake, fails startup with a located `McpError`: a
  configured tool that silently disappeared would hide the misconfiguration. `Runtime.aclose`, and
  every process shape, close the servers alongside the provider.

## Consequences

**Positive**

- A new capability is added at the edge: a configured server's tools appear to the model like any
  other tool, and no `core/` file changes.
- Both boundaries are validated: configuration at load, and every server reply in the client.
- stdio servers never touch the network guard; they are local processes launched from trusted
  configuration, matching the security model's "stdio MCP servers are outside the HTTP guard".

**Negative / accepted costs (deliberate differences, B)**

- **B -- stdio only.** HTTP/SSE MCP servers, and therefore OAuth and remote endpoints, are not
  supported; an HTTP server is not accepted by the schema.
- **B -- fail-fast startup.** A broken server stops the process instead of being skipped, where
  nanobot can carry on without it.
- **B -- no server-initiated flow.** Sampling, roots, and server-to-client requests are ignored;
  only `tools/list` and `tools/call` are used.
- **B -- global allowlist only.** MCP tools obey `[agent].tools`, but there is no per-server tool
  allowlist yet.

## Alternatives considered

- **A lazy client that connects on the first call.** Rejected: tool specs must exist before the
  first turn advertises them to the model, so discovery has to happen at startup anyway.
- **An HTTP/SSE transport in the same slice.** Deferred: it needs SSRF validation before probing and
  before each request, which is a separate boundary and a separate review.
- **Skipping or warning on a broken server.** Rejected: a configured capability that silently
  vanishes is how a misconfiguration reaches production unnoticed.
- **A per-server tool allowlist.** Deferred (ADR-008): the global allowlist already covers
  enablement, and a second knob is only worth adding when a server needs it.
