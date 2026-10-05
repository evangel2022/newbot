# ADR-007: Boundary Guards — Workspace, Network, Sandbox, Access

- Status: Accepted
- Date: 2026-10-05
- Supersedes: —

## Context

newbot operates with filesystem, shell, and network access on the operator's machine. Guarding
only the "main" path is insufficient: every new tool, transport, or MCP endpoint is a potential
bypass. Three classic failure classes must be closed by construction: path escape, server-side
request forgery (SSRF), and unisolated command execution. Additionally, transports are reachable
by others and must not authorize mutations from unconfirmed peers.

## Decision

Centralize each boundary in `policy/` and require every affected path to route through it.

- **Workspace guard (`policy/workspace.py`).** All filesystem path handling resolves through the
  guard and performs an explicit containment check against the effective project workspace with
  read/write capability semantics. Extra roots are capability-specific: read-only roots, write
  roots, and exact-file allowlists are distinct; a write root is never implied by a read root.
- **Network guard (`policy/network.py`).** Every outbound HTTP request from a tool passes the
  shared URL guard. Loopback, RFC1918 private, link-local, CGNAT, and cloud metadata endpoints
  are blocked. The only escape hatch is an explicit operator-configured CIDR whitelist. An
  explicitly configured provider proxy is a separate, authorized trust boundary whose own DNS
  and egress policy applies, while locally identifiable private targets are still rejected.
  HTTP/SSE MCP endpoints are validated before probing and before each request; stdio MCP servers
  are outside the HTTP guard.
- **Shell sandbox (`policy/sandbox.py`).** OS-level isolation is optional and opt-in. On
  platforms where a configured sandbox cannot start, the command fails rather than running
  unisolated. The application-level workspace guard on shell working directories is a separate
  guard and never substitutes for real isolation. Scratch space stays inside the workspace; host
  temporary directories are not shared into a sandbox.
- **Transport access (`policy/access.py`).** Chat and WebSocket transports enforce allowlists,
  pairing, or tokens. Missing or malformed peer metadata means *compatibility unconfirmed*, and
  an unconfirmed core contract cannot authorize mutations.
- **Redaction (`policy/redaction.py`).** Secrets and context-polluting values are stripped before
  they enter persisted memory, session history, or prompts.

**Rule:** any new capability touching paths, network, or process execution must route through the
corresponding guard. A new sandbox backend must match the existing backend contract and preserve
its failure behavior.

## Consequences

**Positive**

- New tools cannot silently bypass a guard; the check lives in one place per boundary.
- Fail-closed behavior makes a misconfigured sandbox safe rather than silently permissive.
- Access control is uniform across transports and is owned by policy, not by the core.

**Negative / accepted costs**

- Guards add a small per-operation cost and must be injected rather than imported as free
  functions.
- Some legitimate local/private targets require explicit whitelisting.
- On Windows, OS-level shell isolation defaults to application-guard-only and requires a
  configured backend for stronger isolation.

## Alternatives considered

- **Per-tool ad hoc checks.** Rejected: easy to forget on a new path; produces inconsistent policy.
- **Rely on OS permissions alone.** Rejected: does not address SSRF or transport access, and
  gives no fail-closed sandbox behavior.
- **Best-effort sandbox that falls back to unisolated execution.** Rejected: a configured sandbox
  that silently does nothing is worse than no sandbox.