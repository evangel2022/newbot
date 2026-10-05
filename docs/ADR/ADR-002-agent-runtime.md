# ADR-002: Turn Engine and Reasoning Loop Split

- Status: Accepted
- Date: 2026-10-05
- Supersedes: —

## Context

An agent turn has two concerns that fail and change for different reasons: the *channel-facing*
concern (session key, workspace scope, context assembly, persistence, outbound delivery) and
the *model-facing* concern (provider call, streaming, tool-call loop, budget). Merging them
produces one large function that is hard to test and where a provider change can break channel
routing. Debugging is also ambiguous: "why did this reply go to the wrong chat?" and "why did
the tool loop stop?" are different questions.

## Decision

Split the runtime into two collaborating components with distinct ownership:

- **`core/turn.py` — `TurnEngine`.** Owns the channel-facing turn: resolves session key and
  effective workspace scope, enqueues per session, assembles context, invokes the reasoning
  loop, persists the turn, and publishes the outbound envelope.
- **`core/reasoning.py` — `ReasoningLoop`.** Owns the model-facing loop: calls the provider,
  streams deltas and reasoning, dispatches tool calls through `ToolRegistryPort`, feeds results
  back, and stops on a final answer or a budget limit.

Rules:

- One active turn per session; additional inbound work is queued, never injected.
- Provider/tool iterations are bounded by an explicit budget; exceeding it yields an incomplete
  result rather than looping forever.
- `ReasoningLoop` performs no persistence and knows no transport; `TurnEngine` performs no
  provider call details and no tool execution.
- Subagent delegation is a separate component (`core/delegation.py`) that drives child turns
  through `TurnEngine` as a service — not by subclassing or embedding the loop.

## Consequences

**Positive**

- Debugging has a clear starting point: routing/session/context → `TurnEngine`; provider,
  streaming, tools, limits → `ReasoningLoop`.
- Each component is unit-testable with a single fake port instead of a full runtime.
- Provider and transport changes are isolated to their adapters.

**Negative / accepted costs**

- Context assembly and turn metadata must be passed explicitly across the boundary; the
  interface between the two components must be kept stable.
- Streaming/progress events require a shared event sink rather than direct callbacks.

## Alternatives considered

- **One monolithic agent loop.** Rejected: conflates two failure domains and grows without
  bound.
- **Provider owns the tool loop.** Rejected: couples tool policy and budgets to each provider
  and duplicates the loop per backend.
- **Runner as a base class extended per scenario.** Rejected: subscriber-side conditionals and
  inheritance hide ownership; subagents are a distinct component, not a subclass.