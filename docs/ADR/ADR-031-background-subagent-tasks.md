# ADR-031: Background Subagent Tasks

- Status: Accepted
- Date: 2026-10-06
- Supersedes: none

## Context

ADR-029 delivered delegation as one in-process child turn the parent waits on, and deferred the
rest of the reference contract (`docs/concepts.md`): background tasks, checking progress,
waiting, and cancelling, with "cancelling one task leaves the others running". The reference also
describes proactive delivery of background results to the origin conversation, persistence across
restart with interrupted marking, and `/stop`, none of which exist yet.

## Decision

Add in-memory background task control; keep proactive delivery and persistence for later.

- `domain/subagent.py` adds `SubagentStatus` (running/completed/incomplete/failed/cancelled) and
  `SubagentTask(id, status, text)`.
- `ports/subagents.py` grows from `run` to `run`/`start`/`status`/`wait`/`cancel`; `run` is
  `start` plus `wait`.
- `core/delegation.py` spawns each child turn as an `asyncio` task and keeps a registry keyed by
  `task-<n>`. `start` returns immediately with a running task; `status` returns a snapshot;
  `wait` awaits the handle; `cancel` cancels one handle and leaves siblings untouched. Every
  control call checks that the caller's session is the task's origin, so another conversation
  cannot read or cancel it. A child still cannot delegate again. `shutdown` cancels every running
  child and is called by `Runtime.aclose`, so the process never leaves a child turn running.
- `tools/delegate.py` gains an `action` (`run` default, plus `start`, `status`, `wait`, `cancel`)
  and renders running/cancelled/incomplete/failed outcomes.
- `Runtime` exposes `subagents`.

## Consequences

**Positive**

- The model can fan out work, keep the conversation going, and later wait on or cancel a task;
  cancelling one child leaves the others running, matching the reference.
- Control is bounded: task ids are per-runtime, ownership is the origin conversation, and
  shutdown cancels everything the runtime started.
- The turn engine is still untouched; only the delegation service and its tool grew.

**Negative / accepted costs (deliberate differences, B)**

- **B -- no proactive delivery.** A finished background task is not pushed to the origin
  conversation; the model must `wait` or `status`. Delivery needs a host that outlives the turn.
- **B -- in-memory only.** The task registry dies with the process, so a restart cannot mark
  interrupted children or retain partial results.
- **B -- no `/stop` and no follow-up instructions.** There is no session-wide stop command and no
  way to send a running child a new instruction.
- **B -- unbounded children.** Background children do not pass through the turn engine, so
  `agent.maxConcurrentTurns` does not bound them.

**Deferred (C)**

- Proactive delivery to the origin conversation, a persistent task registry with interrupted
  marking on restart, `/stop`, follow-up instructions, and bounding background concurrency.

## Alternatives considered

- **Deliver results through the hub now.** Deferred: it forces a runtime "host is alive" decision
  and a delivery-failure policy that this slice does not need.
- **Persist tasks first.** Rejected as the first step: without background execution there is no
  interrupted task to persist.
- **Cancel siblings with the parent.** Rejected: the reference guarantees cancelling one task
  leaves the others running, which the per-handle cancel already provides.
