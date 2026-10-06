# ADR-024: HTTP MCP Transport

- Status: Accepted
- Date: 2026-10-05
- Supersedes: none

## Context

ADR-022 added Model Context Protocol tools at the edge but accepted only stdio servers: an HTTP
endpoint is an outbound network target, and architecture section 12 requires that MCP HTTP/SSE
endpoints be validated before probing and before each request. nanobot
(`docs/guides/configure-mcp-tools.md`, `configuration.md`) configures `tools.mcpServers` entries
with a `url` for HTTP/SSE endpoints and passes them through the SSRF guard. The behavior matrix
recorded HTTP/SSE as **C -- not implemented**.

## Decision

One HTTP client behind the existing `McpClientPort`; the composition root owns the lifecycle.

- `domain/mcp.py` splits the transport spec: `McpStdioServerSpec` keeps `command`/`args`/`env` and
  `McpHttpServerSpec` carries `url`; the shared protocol version moves to
  `MCP_PROTOCOL_VERSION`.
- `adapters/mcp/protocol.py` parses `tools/list` and `tools/call` results once, so both transports
  validate at the same boundary; `adapters/mcp/stdio.py` now uses it.
- `adapters/mcp/http.py` implements the streamable-HTTP transport as `HttpMcpClient`. Requests are
  POST-only, so a non-2xx status is a typed `McpError` rather than a silently absent transport. A
  reply is either one JSON object or an SSE stream whose `data:` messages are parsed and matched by
  JSON-RPC id; a server-assigned `Mcp-Session-Id` is captured from the response headers and echoed
  on every later request; notifications tolerate the spec's `202 Accepted`.
- **SSRF boundary.** Every request calls `NetworkGuard.resolve(url)` first and connects to the
  pinned `connect_url` with the original `Host` header and, for https, the original SNI name, so a
  rebinding resolver cannot redirect the connection after validation. Loopback, private,
  link-local, CGNAT, and metadata targets are rejected unless the operator opens a hole with the
  explicit `tools.ssrfWhitelist`. Validation therefore happens both before the handshake probe and
  before each later request.
- `config/schema.py` accepts `[tools.mcp.servers.<name>]` with exactly one of `command` (stdio) or
  `url` (http/https). Setting both, setting neither, or attaching stdio-only `args`/`env` to a URL
  server is a located `ConfigLoadError`.
- `app/bootstrap.py` selects the client by transport and shares one guard with the rest of the
  composition. A server that cannot be reached fails startup, exactly like a stdio server that
  cannot start (ADR-022).

## Consequences

**Positive**

- A remote MCP server is configured like a local one, and its tools appear under the same
  `mcp__<server>__<tool>` names with no `core/` change.
- The HTTP path is held to the same rules as `web_fetch`: validate and pin on every request, and
  connect only to the pinned address.
- Both transports share one result parser, so boundary validation cannot drift between them.

**Negative / accepted costs (deliberate differences, B)**

- **B -- one URL, POST-only.** A separate SSE endpoint and chunked, incremental result streaming
  are not supported.
- **B -- no OAuth.** Only endpoints that need no OAuth are supported; OAuth is deferred.
- **B -- no server-initiated flow.** Sampling, roots, and server-to-client requests remain
  unsupported (ADR-022).

## Alternatives considered

- **Reuse the `web_fetch` client directly.** Rejected: MCP needs a JSON-RPC session with response
  correlation and session headers, which a fetch wrapper does not model.
- **A separately configured SSE endpoint.** Deferred: streamable HTTP lets the server answer a POST
  with an SSE stream on the same URL, which covers the common servers.
- **Trusting the configured URL without the guard.** Rejected: a configured URL is dynamic input,
  and an operator-supplied endpoint can still address internal services. Architecture section 12
  requires the guard on this path.
