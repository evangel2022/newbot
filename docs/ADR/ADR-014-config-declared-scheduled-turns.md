# ADR-014: Config-Declared Scheduled Turns

- Status: Accepted
- Date: 2026-10-05
- Supersedes: none

## Context

ROADMAP Phase 4 gives `app/scheduler.py` ownership of "timers, heartbeat tasks, session-bound
triggers" and an exit criterion that "a scheduled turn delivers to its origin session". nanobot
documents the equivalent behavior in `docs/automations.md`: automations "are agent turns that run
later in a linked topic" and "deliver back to the session where they were created".

`newbot serve` already runs the `Scheduler` for scheduled curation, and ADR-005 fixes session
identity as `transport:conversation`. A scheduled turn therefore needs a declared origin: the
transport and conversation it belongs to. nanobot also exposes scheduling as a `cron` agent tool
and a `trigger` CLI command, but those need durable job storage and delivery semantics newbot does
not model yet.

## Decision

The long-running host runs **config-declared recurring turns**, each bound to a conversation on the
host transport.

- `ScheduledTurn` (`config/schema.py`) has `everySeconds` (`float > 0`), `conversation` (`str`,
  default `"default"`, non-empty), and `prompt` (`str`, non-empty). A missing or invalid value
  fails fast at load with a field-located `ConfigLoadError`.
- `run_serve` registers one `Scheduler.every(every_seconds, ...)` job per turn, bound to the
  workbench transport (`webui`). The scheduler keeps its existing per-job, sleep-then-run,
  no-overlap semantics.
- Each tick submits a fresh `InboundEnvelope(transport, conversation_id, text=prompt)` through
  `runtime.hub.submit`, so the turn flows through the ordinary `TurnEngine` path: recorded to its
  bound session and emitted through the hub for delivery to any open `/stream` for that
  conversation. No second execution or delivery path is introduced.
- A `NewbotError` from the turn is reported to stderr as `warning: scheduled turn failed: ...`
  and the next tick still runs; a failed delivery is not retried within the tick.

## Consequences

**Positive**

- Scheduling reuses the existing `Scheduler`, hub, and turn engine; the core stays unchanged.
- A scheduled turn is indistinguishable from a transport-originated turn: it is persisted to its
  origin session (ADR-005) and delivered on the ADR-011 stream.
- Failures are observable and bounded; a recurring job cannot spin on a permanent error.

**Negative / accepted costs**

- Delivery is best-effort: with no `/stream` open for the conversation the reply is still recorded
  but not pushed, matching the workbench's existing guarantee.
- Scheduling is declared in configuration and needs a host restart to change; there is no durable
  job store.
- Each tick is a new turn rather than a deduplicated at-least-once trigger, so consumers do not
  receive an idempotency key.

## Alternatives considered

- **A `cron` agent tool (nanobot's surface).** Deferred: it needs durable job storage, per-job
  ownership, and delivery/result semantics the core does not model yet (Phase 5
  `tools/schedule.py`).
- **A `trigger` CLI command.** Deferred: firing one turn from the CLI duplicates `run -m` against
  the bound conversation and adds no scheduling.
- **Reusing the curation interval.** Rejected: curation is a fixed maintenance job, not
  user-declared turns, and conflating them would couple unrelated intervals.
- **Delivering straight to the transport, bypassing the hub.** Rejected: it would create a second
  turn path and skip session recording.
