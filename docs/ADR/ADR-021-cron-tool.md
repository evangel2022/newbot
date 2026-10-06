# ADR-021: Agent-Created Scheduled Jobs

- Status: Accepted
- Date: 2026-10-05
- Supersedes: none

## Context

nanobot's `automations.md` gives the agent a `cron` tool that creates, lists, and removes scheduled
work, keeps a protected heartbeat job that `cron(action="list")` shows but cannot remove, and
persists jobs under the workspace so they survive a restart. newbot already runs config-declared
recurring turns (ADR-014), a config-declared heartbeat (ADR-019), and consumed local triggers
(ADR-018), but the agent itself could not create a job; the behavior matrix records the `cron` tool
as **C -- not implemented**.

## Decision

One model-facing tool, `cron`, backed by a durable registry and a host poller that reuses the hub
and turn engine.

- `domain/job.py` adds `ScheduledJob` (id, transport, conversation, prompt, `next_run_at`,
  `every_seconds`) and a `Clock`/`utcnow` seam so scheduling is testable without wall time.
- `ports/jobs.py` defines `JobStorePort`. `adapters/stores/json_jobs.py` implements it as one
  `<workspace>/cron/jobs.json` file per workspace: read-modify-write of that single file under a
  process-wide lock, written atomically so a crash never leaves a partial registry. Every record is
  validated at the storage boundary with pydantic (`extra="forbid"`, `next_run_at` must be
  timezone-aware, `every_seconds` must be positive). A registry that cannot be parsed or that holds
  an unusable record is quarantined as `cron/jobs.invalid.json` (the ADR-018 delivery-file policy)
  and read as empty, so one corrupt file cannot wedge every poll.
- `tools/cron.py` owns the model-facing contract. `action` is `add`, `list`, or `remove`. `add`
  needs a `prompt` and exactly one of `every_seconds` (recurring) or `delay_seconds` (one-shot), and
  binds the job to the calling session (`ctx.session`), so a job always fires where it was created.
  `remove` takes a `job_id`. There is no pause, resume, or run-now.
- `app/cron.py`'s `CronRunner.dispatch` asks the store for the due jobs and submits each as an
  `InboundEnvelope` to the hub. `app/lifecycle.py` registers one poller (`_CRON_POLL_SECONDS = 1`)
  whenever `serve` runs. The registry is advanced *before* a turn is submitted, so a crash or a
  failed turn never replays a run; a failed job is warned and the next job in the same tick still
  runs. A job runs only while a host is serving, and the tool says so in its reply.
- Recurring jobs schedule their next run from the dispatch time, so runs missed while the host was
  down are skipped instead of replayed as a burst; an overdue one-shot job runs once and is dropped.
- `core/hub.py` now raises `TransportError` (a `NewbotError`) when an outbound reply names an
  unregistered transport, so `TurnEngine` marks the turn failed instead of leaking an unhandled
  `RuntimeError` through the caller. This is the structure the poller needs to survive a job bound
  to a transport that is not currently registered.

## Consequences

**Positive**

- The agent can create durable work that survives a restart of the host, and that work runs through
  the same turn engine, per-session serialization, and concurrency bound as any other turn.
- Scheduling is deterministic in tests: the store and the runner both take a `Clock`.
- Both boundaries are validated: the model's tool arguments at the tool, and the on-disk registry
  at the store.

**Negative / accepted costs (deliberate differences, B)**

- **B -- session-bound jobs.** A job belongs to the conversation that created it. newbot has no
  cross-process scheduler daemon, so jobs fire only while `newbot serve` runs.
- **B -- no pause/resume/run-now.** The tool can add, list, and remove only.
- **B -- the heartbeat is invisible to the tool.** nanobot's `cron(action="list")` also shows the
  protected heartbeat job and cannot remove it; newbot's `cron` lists only agent-created jobs, and
  the heartbeat stays a separate config-declared concern (ADR-019).
- **B -- interval and one-shot only.** No cron expressions, timezones, or absolute scheduling.

## Alternatives considered

- **A cross-process scheduler daemon.** Rejected: newbot's host is a single `serve` process, and a
  second daemon would duplicate ownership of the registry and the session locks.
- **Replaying every missed run.** Rejected: a host that was down for a day would run a burst of
  turns on startup; skipping to the next interval is the safer default.
- **A cron-expression parser.** Deferred (ADR-008): interval and delay cover the request, and a
  parser is a large contract to add before a caller needs it.
- **Keeping the unregistered-transport `RuntimeError`.** Rejected: an internal exception escaping
  the turn made a failed job indistinguishable from a crash; a typed `TransportError` is the
  boundary's real contract.
