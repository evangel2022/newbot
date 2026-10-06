# ADR-017: Failed Outbound Delivery Is a Terminal Turn Failure

- Status: Accepted
- Date: 2026-10-05
- Supersedes: none

## Context

`docs/architecture.md` §6.3 states that "a turn that reaches the agent but fails is marked failed,
not retried forever", and the ROADMAP Phase 4 exit criteria repeat "a failed delivery is marked
failed, not retried forever". nanobot's `docs/automations.md` is explicit: "If the delivery reaches
the agent and the turn fails, the delivery is marked failed instead of retrying forever."

`TurnEngine._run_turn` guarded the reasoning phase and published `TurnFailed` on a `NewbotError`,
but the outbound `hub.emit` call ran *outside* that guard. A transport whose `deliver` raised
`TransportError` (a `NewbotError`) therefore escaped `handle`: subscribers received `TurnStarted`
and then no terminal event, the WebSocket stream never learned the turn had ended, and the reply —
already persisted to the session — was never marked.

## Decision

A deliberate (`NewbotError`) failure from outbound delivery is terminal.

- `_run_turn` catches a `NewbotError` raised by `hub.emit`, publishes `TurnFailed`, and returns.
  `TurnCompleted` is not published, and the delivery is not retried.
- The reply is still persisted, because the session write happens before delivery; the session
  remains the source of truth for a reply that could not be delivered.
- Failures that are not `NewbotError` (for example, no transport registered for the origin) still
  propagate: those are broken internal invariants, not supported recovery paths (C4).

## Consequences

**Positive**

- Every started turn now ends in exactly one terminal event, so subscribers and streams cannot be
  left waiting on a turn that already finished.
- The documented contract is enforced: a failed delivery is marked failed and never retried.
- The workbench stream receives an `error` frame on a delivery failure instead of silence.

**Negative / accepted costs**

- A delivery failure is reported as a turn failure even though reasoning succeeded; consumers that
  need the distinction must read the session.
- The reply is not redelivered. At-least-once delivery remains the transport's contract, so a
  transport that wants retries must own them rather than relying on the engine.

## Alternatives considered

- **Retry the delivery inside the engine.** Rejected: it contradicts "not retried forever", and
  duplicates a policy the transport owns.
- **Add a dedicated delivery-failure event.** Rejected: a new event type for one terminal case,
  when `TurnFailed` already means "this turn will not complete".
- **Swallow the failure and publish `TurnCompleted`.** Rejected: it hides a real failure and would
  report a delivered reply that was never delivered.
