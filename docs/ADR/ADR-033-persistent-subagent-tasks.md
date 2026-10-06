# ADR-033: Persistent Subagent Task Registry

- Status: Accepted
- Date: 2026-10-06
- Supersedes: none

## Context

ADR-031 and ADR-032 gave subagents background control and delivery, but the task registry lived
only in memory: a restart forgot every task and could not tell a running child from a finished
one. The reference (`docs/concepts.md`) says saved task history and results remain available
after a restart, unfinished tasks are marked interrupted with saved partial results, and newbot
does not automatically resume them.

## Decision

Persist the registry in the workspace and mark interrupted tasks on load.

- `domain/subagent.py` adds `SubagentStatus.INTERRUPTED` and `SubagentTaskRecord(id, parent,
  child, status, text)`; `ports/subagents.py` adds `SubagentTaskStorePort` (`load`/`save`).
- `adapters/stores/json_subagent_tasks.py` stores `<workspace>/subagents/tasks.json`. Writes are
  atomic under a process lock, and a file that cannot be parsed or that holds an invalid record
  is quarantined as `tasks.invalid.json` (the ADR-018 delivery-file policy) instead of wedging
  startup. The parent and child sessions are stored as transport plus conversation.
- `SubagentManager` takes an optional store. On construction it loads the records, turns every
  `running` record into `interrupted` (and persists the change), restores the id counter so a new
  task cannot reuse an id, and seeds the child set. Every spawn and every state change persists.
- A `_RecordingSink` captures the child's streamed text, so a cancelled task keeps its partial
  reply; a task that hits the iteration limit keeps the final partial too.
- A store write failure is a typed `SubagentError`.
- The `delegate` tool renders an interrupted task with its partial reply.

## Consequences

**Positive**

- Task outcomes and partial replies survive a restart; a parent can inspect an interrupted child
  and start a new task to continue the work, matching the reference.
- Interrupted marking is deterministic: only a record left `running` becomes `interrupted`;
  completed, failed, cancelled, and incomplete outcomes are preserved verbatim.
- Ids never collide across restarts, and one corrupt registry cannot stop every startup.

**Negative / accepted costs (deliberate differences, B)**

- **B -- no auto-resume.** Interrupted tasks are recorded, not restarted; this matches the
  reference, so it is a Match rather than a gap.
- **B -- partial "when available".** A cancelled or incomplete task keeps streamed text; a hard
  crash persists only the pre-turn `running` record, so its partial reply may be empty.
- **B -- workspace-scoped file.** The registry lives under the workspace (`subagents/tasks.json`)
  like the cron registry, while session history lives under the config directory.

**Deferred (C)**

- `/stop`, follow-up instructions to a running child, a dedicated out-of-turn delivery event, and
  a background concurrency bound.

## Alternatives considered

- **Store under the config directory next to sessions.** Rejected for consistency with the
  workspace-scoped cron registry; a workspace path is what the operator can inspect.
- **Persist after every iteration for finer partials.** Deferred: it needs an iteration callback
  from the reasoning loop and per-iteration I/O; the streamed-text sink is enough for the common
  cancellation path.
- **Resume interrupted tasks on startup.** Rejected: the reference explicitly does not auto-resume,
  and automatic execution on startup is a surprising capability.
