# ADR-003: Tool Contract, Registry, and Policy Injection

- Status: Accepted
- Date: 2026-10-05
- Supersedes: —

## Context

Tools are how the model affects the world (files, shell, network, external servers) and are the
primary security surface. Three problems must be solved together: (1) the model needs a stable
name/schema contract; (2) new tools must be addable without touching the core; (3) every
safety-relevant operation must pass a guard on *every* path, not just the common one.

## Decision

Define one tool contract and one registry, with guards injected through a context object.

- **Contract (`tools/base.py`).** A tool exposes a stable `name`, a `description`, a JSON-schema
  parameter spec, and `async invoke(args, ctx) -> ToolResult`. Names, schemas, and error
  messages are model-facing contract and change only intentionally.
- **Context (`ToolContext`).** Carries the resolved workspace scope, explicit read/write
  capabilities, `policy` guards, the event sink, a cancellation token, and the owning session.
  Tools receive only what they need and never read global state.
- **Registry (`tools/registry.py`).** Deterministic discovery from built-in modules and explicit
  entry points, filtered by the agent's allowlist. No import-time side effects silently enable
  a tool; discovery is traceable from config to the concrete tool.
- **Policy injection.** Filesystem, shell, and web tools call the corresponding guard on every
  path. A tool may not perform raw path resolution or raw HTTP. Tool results are bounded and
  sanitized before entering model context.

## Consequences

**Positive**

- Adding a tool is local: implement the contract, register it, optionally whitelist it.
- Safety is enforced once in `policy`, so a new tool cannot accidentally bypass a guard.
- The tool contract is stable and testable without a running agent.

**Negative / accepted costs**

- Every tool invocation carries a context object; authors must use it rather than shortcuts.
- Registry discovery needs care to stay deterministic and side-effect free.

## Alternatives considered

- **Decorator/import-time auto-registration.** Rejected: hidden capability, contradicts A3.
- **Tools call security helpers directly.** Rejected: duplicated and easily forgotten on a new
  path; centralizing in `policy` with injection is safer.
- **One giant built-in tool module.** Rejected: mixes unrelated capabilities and their guards.