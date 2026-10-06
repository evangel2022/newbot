# ADR-029: In-Process Delegation

- Status: Accepted
- Date: 2026-10-06
- Supersedes: none

## Context

Phase 5's remaining exit criterion is delegation: subagents with isolated context that report back
to their origin session. The reference (`docs/concepts.md`) describes the full contract:
background tasks deliver results to the conversation that started them, a task can be checked,
instructed, waited on, or cancelled, cancelling one leaves siblings running, unfinished tasks
survive restart marked interrupted with partial results, and single-turn CLI/SDK calls wait for
results when background delivery is unavailable. The architecture (`core/delegation`,
`SubagentManager`) expects child sessions and a task registry.

Building the whole contract at once would need a persistent task registry, background delivery,
cancellation, and restart recovery. This ADR takes the wait-for-result half first, which the
reference already names as the single-turn behavior, and leaves the background half as a
deferred deliverable.

## Decision

Delegate as one in-process child turn that the parent waits on.

- `ports/subagents.py` defines `SubagentPort` and `SubagentOutcome(text, status)`. The port keeps
  the `tools` layer from importing `core`.
- `tools/delegate.py` adds `DelegateTool` (name `delegate`, argument `task`). It returns the
  child's reply, marks a child that hit its iteration limit, and turns a failed child into a
  tool error.
- `core/delegation.py` adds `SubagentManager`, implementing the port. It reuses the shared
  `ReasoningLoop` and `ContextAssembler`, so the child runs the same model/tool loop. The child
  session is derived (`<conversation>:sub:<n>`), its context is only the task message, it uses
  the shared tool registry, and its `(task, *produced)` messages are recorded to the child
  session. Child events are discarded: the reply returns through the tool call.
- A child cannot delegate a further task: the manager refuses a parent that is already one of its
  children, so delegation cannot recurse.
- The composition root constructs the manager before the registry (the tool holds it) and calls
  `bind(reasoning, assembler)` once they exist. That single deferred binding keeps the object
  graph acyclic; the registry gains a `subagents` parameter.

## Consequences

**Positive**

- A parent can hand a self-contained task to a child with isolated context and get a result,
  which is the reference's single-turn CLI/SDK behavior.
- The child shares the tool registry and the model request path, so tools, guards, and the
  system prompt behave identically; no new capability surface appears on the child.
- The `turn` engine is untouched: delegation is one more edge tool plus a core service bound at
  composition.

**Negative / accepted costs (deliberate differences, B)**

- **B -- wait-only.** There is no background delivery, no progress/control commands, no
  cancellation, and no `/stop`; the parent blocks until the child turn finishes.
- **B -- no persistence.** Child history is recorded per session, but the task registry is
  in-memory, so a restart does not mark interrupted children or retain partial results.
- **B -- flat, derived child keys.** A child is `<parent>:sub:<n>` on the same transport and is
  not distinguishable in search from a user session yet.
- **B -- child events are dropped.** The reply reaches the model through the tool result; the
  origin conversation sees no child progress events.

**Deferred (C)**

- Background delivery, task status/instruction/wait/cancel commands, `/stop`, persistent task
  registry with interrupted marking and partial results, and child-event surfacing.

## Alternatives considered

- **Implement the full background contract now.** Deferred: it needs a durable task registry and
  a delivery path, and the wait-only half is independently useful and testable.
- **A child turn as a plain second provider call (no tools).** Rejected: it would not match the
  reference, where subagents are themselves agents with tools.
- **Give `DelegateTool` the `TurnEngine` directly.** Rejected: it would couple the tool to the
  transport-facing engine and create a construction cycle with the registry.
- **Let a child delegate again with a depth budget.** Deferred: depth tracking belongs with the
  background task registry; the hard refusal is the smallest correct guard for now.
