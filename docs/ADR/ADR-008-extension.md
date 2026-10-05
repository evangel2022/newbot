# ADR-008: Extension Points at the Edges

- Status: Accepted
- Date: 2026-10-05
- Supersedes: —

## Context

newbot must grow (new providers, transports, tools, skills, external MCP servers) without
expanding the core path or fragmenting into ad hoc wiring. At the same time, extension mechanisms
must not become hidden capability: an operator must be able to trace what is enabled to a
concrete implementation, and an extension must not be able to reach into core internals.

## Decision

Define a small number of named extension points, all at the edges, each with an explicit boundary
and registration path.

| Extension | How it is added | Boundary |
| --- | --- | --- |
| Provider | Register a spec + implement `ProviderPort` | `adapters/providers` |
| Transport | Implement `TransportPort`; export a descriptor | `adapters/transports` |
| Tool | Implement the tool contract under `tools/` or an entry point | `tools` |
| Skill | Markdown + YAML frontmatter under workspace `skills/` or built-ins | `extensions/skills` |
| Plugin | Package bundling skills and/or MCP servers | `extensions/plugins` |
| MCP server | Config entry or bundled in a plugin | `tools/mcp` |
| Scheduler job | Register with the scheduler; workspace-scoped | `app/scheduler` |

Rules:

- Prefer the existing registry/discovery patterns over ad hoc wiring (A3).
- Capability that is "know-how" rather than code belongs in a skill, not in the agent loop (A1).
- Extension discovery is deterministic and side-effect free; enabled extensions are traceable
  from config to the concrete class.
- MCP/plugin connection lifecycle is owned by the composition root: connect before use, close on
  shutdown. The core never manages connection lifecycle.
- Adapters may duplicate similar logic (retries, media handling, splitting) rather than share a
  base class (A5).

## Consequences

**Positive**

- The core change surface stays small; most growth is additive at the edges.
- Operators can see exactly what is enabled and where it comes from.
- New transports/providers do not require touching the execution path.

**Negative / accepted costs**

- Some duplication across adapters is intentional and must be maintained deliberately.
- Each extension point needs a stable contract and a documented manifest shape.

## Alternatives considered

- **Single universal plugin interface for everything.** Rejected: providers, tools, and
  transports have fundamentally different contracts; one interface would be a lowest-common
  denominator and would leak core concerns.
- **Import-time auto-discovery of arbitrary packages.** Rejected: hidden capability and unclear
  provenance (A3).
- **Everything as MCP.** Rejected: MCP is the right edge for external tools, but built-in tools,
  providers, and transports are first-party contracts, not remote servers.