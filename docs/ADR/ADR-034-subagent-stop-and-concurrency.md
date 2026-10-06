# ADR-034: Subagent Stop Command and Concurrency Bound

- Status: Accepted
- Date: 2026-10-06
- Supersedes: none

## Context

ADR-031 deferred `/stop` and a background concurrency bound. The reference
(`docs/concepts.md`) says "Use `/stop` to stop the current session and its subagents. Other
sessions are unaffected", and background children in newbot bypass `TurnEngine`, so
`agent.maxConcurrentTurns` (ADR-015) did not bound them at all.

## Decision

Add a session-scoped stop and a child-turn concurrency bound.

- `SubagentManager.cancel_session(parent)` cancels every running task owned by that session and
  returns the tasks it stopped. Ownership already scopes tasks to their origin conversation, so
  other sessions are untouched.
- The interactive CLI gains `/stop`, which cancels the current session's running children and
  prints how many stopped (or that none were running). It is listed in `/help`.
- `SubagentManager(max_concurrent=...)` bounds concurrently *running* child turns with an
  `asyncio.Semaphore` acquired around the child reasoning run, so `start` still returns
  immediately and extra tasks wait instead of failing. The composition root passes
  `agent.maxConcurrentTurns`.

## Consequences

**Positive**

- An operator can stop a session's delegated work without killing the process or other sessions.
- Child turns are bounded like parent turns, so background delegation cannot fan out without
  limit when the operator set a bound.

**Negative / accepted costs (deliberate differences, B)**

- **B -- a separate semaphore.** Subagents share the `maxConcurrentTurns` value but not the turn
  engine's semaphore, so the process can run up to that many parent turns plus that many children;
  it is a per-kind bound, not one global cap.
- **B -- CLI-only command.** `/stop` is wired into the interactive terminal; chat-channel command
  handling is not implemented, so a Telegram `/stop` is still sent to the model.
- **B -- running tasks only.** `cancel_session` cancels tasks that are running in this process;
  a restored interrupted task is already terminal.

**Deferred (C)**

- Follow-up instructions to a running child, a dedicated out-of-turn delivery event, and
  chat-channel command handling.

## Alternatives considered

- **One global semaphore shared with the turn engine.** Deferred: it needs the engine to expose
  its semaphore or a shared limiter, which couples the manager to the transport-facing engine.
- **A new `agent.maxConcurrentSubagents` key.** Rejected: `maxConcurrentTurns` already names the
  intent, and child runs are turns.
- **Cancel via the `delegate` tool action only.** Rejected for this slice: a session-wide stop is
  the reference command, and the tool already covers single-task cancel.
