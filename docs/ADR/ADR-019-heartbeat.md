# ADR-019: Workspace Heartbeat

- Status: Accepted
- Date: 2026-10-05
- Supersedes: none

## Context

`docs/architecture.md` gives the scheduler "timers, heartbeat tasks, and session-bound external
triggers", and the ROADMAP Phase 4 deliverable names `app/scheduler.py` with the same three jobs.
Timers (ADR-014) and session-bound triggers (ADR-018) exist; heartbeat remains.

nanobot's published contract (`configuration.md#gateway-heartbeat`, `chat-commands.md#periodic-tasks`,
`automations.md#heartbeat`) is: a protected background job reads `<workspace>/HEARTBEAT.md`; if the
file has tasks under `## Active Tasks`, the agent executes them and sends only useful or actionable
results to the most recently active chat target; otherwise the heartbeat is skipped silently.
Configuration is `gateway.heartbeat.{enabled, intervalS, keepRecentMessages}` with the job enabled by
default. The notification gate is an LLM evaluator: a custom prompt must still call
`evaluate_notification`, and the gate fails closed to silence.

newbot has no notification-gate tool and no chat channel from which to pick a "most recently active
target", so v1 has to define delivery without an evaluator.

## Decision

A config-declared heartbeat runs workspace tasks quietly in a dedicated conversation.

- Configuration adds `[heartbeat]`: `enabled` (default `false`), `intervalSeconds` (default `1800`,
  must be `> 0`), and `conversation` (default `"heartbeat"`). The job is opt-in, like
  `schedule.turns` and `triggers.items`.
- `app/heartbeat.py` owns interpreting the workspace file. `read_active_tasks` returns the
  top-level `-`/`*`/`+` bullets under the exact `## Active Tasks` heading, stopping at the next
  `##` heading. A missing file, an absent section, and a bullet-free section all return no tasks.
- `run_serve` registers `_heartbeat_job` on the scheduler only when heartbeat is enabled. Each tick
  re-reads the file: with no tasks it does nothing; with tasks it submits one turn on the host
  (workbench) transport into `heartbeat.conversation`, whose text lists the active tasks.
- The heartbeat turn is **recorded** into its session but **never delivered**. `InboundEnvelope`
  gains `reply: bool = True`, and `TurnEngine` emits the outbound reply only when `reply` is true.
  `TurnStarted`/`ResponseDelta`/`TurnCompleted` still publish; `reply = false` suppresses only the
  final reply envelope. No client subscribes to the heartbeat conversation, so a run is silent.
- An unreadable or undecodable `HEARTBEAT.md`, and a failed heartbeat turn, are reported as a
  `warning:` on stderr without stopping the host; the next tick retries.

## Consequences

**Positive**

- Delivery reuses the scheduler, hub, and turn engine, so per-session serialization and the
  cross-session bound still apply and there is no second execution path.
- `HEARTBEAT.md` is the only new dynamic input and it is validated at the boundary: unknown or
  malformed content degrades to "no tasks" instead of raising into the scheduler.
- Recording the turn lets a task compare against earlier runs ("notify only if something changed")
  without a separate store.

**Negative / accepted costs (deliberate differences, B)**

- **B -- always silent.** nanobot gates notifications with an LLM evaluator (`evaluate_notification`);
  newbot v1 has no gate, so a heartbeat never delivers. `reply = false` is the explicit mechanism.
  The notification gate, `keepRecentMessages`, and a custom evaluator prompt are **C -- not
  implemented**.
- **B -- opt-in.** nanobot enables the job by default; newbot defaults `heartbeat.enabled = false`.
  Because v1 stays silent, a default-on job would spend provider calls with no visible result.
- **B -- fixed target.** nanobot delivers to the most recently active chat target; newbot binds a
  config `conversation` on the host transport, as ADR-014 and ADR-018 already do, because there is
  no channel-activity tracking.
- **B -- no `cron` visibility.** nanobot's heartbeat shows in `cron(action="list")` and cannot be
  removed with the tool; newbot has no `cron` tool, so there is nothing to list (ADR-018).
- A heartbeat consumes a turn slot like any other turn, so `agent.maxConcurrentTurns` bounds it.

## Alternatives considered

- **Deliver every heartbeat result.** Rejected: the reference contract is that a heartbeat usually
  stays quiet; routine results would spam the conversation.
- **An LLM notification gate now.** Deferred: it needs an `evaluate_notification` tool and a
  fail-closed evaluator prompt. The explicit `reply` flag is the honest v1 and fails closed to
  silence.
- **A no-op transport for the heartbeat conversation.** Rejected: it fakes an execution path
  instead of stating that this turn has no reply target. "Does this request want a reply" is a
  property of the inbound request.
- **One turn per task instead of one turn per tick.** Rejected: nanobot treats the file as one
  check, and one turn per tick keeps the scheduler contract unchanged.
- **Watching `HEARTBEAT.md` for changes instead of polling.** Rejected: the interval is the
  documented contract and the scheduler already provides it.
