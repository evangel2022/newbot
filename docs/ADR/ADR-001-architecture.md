# ADR-001: Hexagonal Architecture with a Small Core

- Status: Accepted
- Date: 2026-10-05
- Supersedes: —

## Context

newbot must support many model providers and many transports (terminal, web workbench, chat
apps) without multiplying execution logic, and must extend capability (tools, skills, MCP,
scheduling) without destabilizing the agent path. Comparable runtimes demonstrate that a
single narrow execution core shared by multiple thin surfaces is what keeps behavior
consistent and reviewable. newbot must derive this structure independently, not inherit any
project's module layout.

## Decision

Adopt a hexagonal (ports-and-adapters) architecture with strict inward dependencies:

```
domain ← ports ← core ← adapters ← app ← cli
                   ▲
                 policy
```

- `domain` holds pure value types and typed errors, with no dependencies.
- `ports` declares the interfaces `core` needs; it depends only on `domain`.
- `core` is the small execution path (turn engine, reasoning loop, context, delegation, hub).
- `policy` is a leaf set of security guards with no knowledge of adapters.
- `adapters` implement ports for providers, transports, and stores.
- `app` is the composition root; `cli` only parses and dispatches.

The core communicates with the world exclusively through ports. `core` and `adapters` are
mutually forbidden from importing each other's internals, enforced by review and import lint.

## Consequences

**Positive**

- A capability that can live at the edge (tool, transport, provider, skill, MCP, plugin) never
  enters the core path; the core's change surface stays small and reviewable.
- The same execution logic serves every transport, so behavior is consistent and one fix
  applies everywhere.
- Adapters are independently testable with fake ports; the core is testable without any I/O.

**Negative / accepted costs**

- More indirection: simple features may cross several layers.
- The ports must be designed up front; changing a port touches all adapters.
- Some duplication across adapters is accepted rather than abstracted (see ADR-008 / A5).

## Alternatives considered

- **Layered-by-feature (agent/**, channels/**, tools/** directly importing each other).**
  Rejected: invites core growth and cross-adapter coupling; the agent path accumulates
  transport- and platform-specific conditions.
- **Plugin-event-bus with no explicit core.** Rejected: hides control flow and state ownership;
  contradicts "explicit over magical" (A3).
- **Shared base classes across adapters to remove duplication.** Rejected: premature
  abstraction (A5); adapters become coupled and harder to read alone.