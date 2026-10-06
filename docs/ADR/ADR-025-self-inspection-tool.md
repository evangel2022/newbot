# ADR-025: Read-only Self-Inspection Tool (my)

- Status: Accepted
- Date: 2026-10-05
- Supersedes: none

## Context

Phase 5 adds self-inspection at the edge: the agent should be able to answer "what model am I,
where is my workspace, what limits apply" without reading process-global state. nanobot
(`docs/my-tool.md`) ships a `my` tool with `check` and `set`: `check` returns a config overview
(with blocked and sensitive keys) and `set` tunes mutable runtime parameters and a session
scratchpad.

## Decision

One read-only tool, with the snapshot assembled by the composition root.

- `tools/self.py` adds `MyTool` (name `my`). It supports `action="check"` only, so a turn cannot
  mutate shared runtime state; an optional `key` returns one top-level field instead of the
  overview.
- The snapshot is built by `app/bootstrap.py` from configuration (`model`, `provider`,
  `max_iterations`, `sandbox`, `shell_timeout_seconds`, `allowed_tools`, `mcp_servers`) and passed
  to the registry. The tool adds the per-turn `workspace` and `session` from its `ToolContext`, so
  it never reads process-global state.
- **No secrets.** Only non-secret fields enter the snapshot; provider keys, channel tokens, and MCP
  `env` values are never included (the values `configured_secrets` redacts). The output is
  deterministic, sorted `key: value` lines with JSON-encoded values.
- The tool is registered only when a snapshot is supplied, so it is present in the real runtime and
  absent from registries built without one.

## Consequences

**Positive**

- The agent can report its own model, workspace, session, and limits, making self-diagnosis ("why
  can't you search the web?") possible without a special prompt.
- Secrets cannot leak through the tool: the snapshot is an allowlist of fields, not a dump of the
  settings object.
- The core is untouched; self-inspection is one more edge tool.

**Negative / accepted costs (deliberate differences, B)**

- **B -- read-only.** nanobot's `set`/runtime tuning, session scratchpad, token-usage reporting,
  and subagent monitoring are not supported. Tuning would let one turn change the shared instance
  default, which conflicts with a configuration resolved once at startup.
- **B -- config view, not live state.** The snapshot reflects resolved configuration plus the
  turn's session and workspace; it does not report live token usage or running subagents.

## Alternatives considered

- **Passing the whole `Settings` object to the tool.** Rejected: it makes accidental secret
  disclosure a one-line mistake; an explicit allowlist of fields is safer.
- **Reading runtime state from the registry or core.** Rejected: tools must not reach into global
  state, and the composition root already knows these facts.
- **Supporting `set` for `max_iterations`.** Deferred: the limit is part of the per-turn budget
  fixed at composition; changing it mid-turn is a core-semantics change, not a tool.
