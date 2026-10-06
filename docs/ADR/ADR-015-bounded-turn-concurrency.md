# ADR-015: Bounded Cross-Session Turn Concurrency

- Status: Accepted
- Date: 2026-10-05
- Supersedes: none

## Context

`docs/architecture.md` §6.3 states that "cross-session parallelism is allowed but bounded by a
global worker limit", and ROADMAP Phase 4 lists "per-session serialization and bounded
cross-session parallelism" as a deliverable. The turn engine already serializes turns per session
(ADR-002), but it left cross-session turns unbounded: every distinct `SessionKey` could start a
provider call immediately, so a client opening many conversations could drive unbounded concurrent
model requests.

nanobot documents the equivalent knob as the environment variable `NANOBOT_MAX_CONCURRENT_REQUESTS`
("Maximum concurrently running inbound agent requests"; unset, `0`, or a negative value means
unlimited). newbot configures through TOML, so the bound needs a typed configuration field.

## Decision

`agent.maxConcurrentTurns` (`int > 0`, default `None`) caps how many turns run at once across
sessions. `None` means unlimited, matching nanobot's documented default.

- `TurnEngine` takes `max_concurrent_turns: int | None`. When set, a shared `asyncio.Semaphore`
  bounds the number of `_run_turn` bodies in flight; when `None`, no semaphore is created.
- The semaphore is acquired *after* the per-session lock, so turns queued behind an active session
  wait on that lock without occupying a slot. Per-session serialization is unchanged.
- `build_runtime` passes `settings.agent.max_concurrent_turns`.
- `0` and negative values are rejected at load with a field-located `ConfigLoadError`; unlimited is
  expressed by omitting the field, consistent with newbot's strict configuration (ADR-006).

## Consequences

**Positive**

- The runtime now enforces the concurrency limit its architecture already documents.
- An operator can cap concurrent provider load without touching the core or the transports.
- Per-session serialization and the resulting reply ordering are unchanged; the bound only delays
  *when* a queued turn starts.

**Negative / accepted costs**

- With a finite bound, later turns queue; a bound below the real parallelism can add latency.
- newbot rejects `0`/negative instead of reading them as unlimited, a deliberate strictness
  difference from nanobot (recorded in the behavior matrix).
- The semaphore is process-local, so multiple hosts do not share a limit.

## Alternatives considered

- **A hardcoded constant bound.** Rejected: the right limit depends on the provider and deployment,
  so it belongs to the operator, and a hardcoded value would silently change behavior.
- **An environment variable, as nanobot does.** Rejected: newbot resolves configuration through
  typed TOML with located errors (ADR-006); an env-only knob would sit outside that boundary.
- **Bounding in the hub or transport instead of the engine.** Rejected: the engine already owns
  per-session serialization, so cross-session bounding belongs in the same place and reuses the
  same lifetime.
