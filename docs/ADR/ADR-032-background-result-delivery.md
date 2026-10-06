# ADR-032: Background Result Delivery

- Status: Accepted
- Date: 2026-10-06
- Supersedes: none

## Context

ADR-031 added background subagent tasks (`start`/`status`/`wait`/`cancel`) but no way for a
finished task to reach the origin conversation: the model had to poll. The reference
(`docs/concepts.md`) says "Background tasks return their results to the conversation that started
them", and for single-turn CLI/SDK calls "wait for results when background delivery is
unavailable".

newbot has no "out-of-turn assistant message" event. Transports render a turn in two ways:
`EventSink.publish` carries streamed `ResponseDelta`/`TurnCompleted` events (the CLI and the
workbench stream render text from deltas), while `EventHub.emit` carries the authoritative
`OutboundEnvelope.text` and is consumed by message transports (Telegram) and to resolve a pending
workbench request.

## Decision

Deliver a background result through both existing paths.

- `SubagentManager` takes the `EventHub`. When a task started with `start` finishes with text, it
  publishes `ResponseDelta(session=parent, text=...)` and then `emit`s an `OutboundEnvelope` to
  the origin transport and conversation. Streaming transports render the delta; message
  transports send the envelope text.
- A synchronous `run` never delivers: its reply returns through the tool result.
- The publish/emit runs inside the child task, so `wait`/`drain` observe the delivered state and a
  caller that started and then waited does not race delivery.
- A delivery failure is terminal: the task's status becomes `failed` with the transport error,
  matching ADR-017.
- Foreground lifecycle drains before closing: `run_once` and `run_interactive` call
  `SubagentManager.drain()` before `aclose()`, so a one-shot or interactive exit waits for
  outstanding children (the reference's single-turn behavior). The long-running host keeps
  cancelling on close; it cannot yet mark interrupted children.

## Consequences

**Positive**

- A background task reports its result to the conversation that started it, without the model
  polling, for every transport that can render a delta or send an envelope.
- No new transport contract: delivery reuses the delta stream and the outbound envelope exactly
  as a normal turn does.
- Delivery failures are visible as a failed task rather than a swallowed error.

**Negative / accepted costs (deliberate differences, B)**

- **B -- reuses two paths, not one.** There is no dedicated out-of-turn message event; a streaming
  client sees a `ResponseDelta` without a preceding `TurnStarted`, which the workbench stream
  tolerates but does not label as a subagent result.
- **B -- host restart loses running tasks.** The task registry is still in-memory, so the host
  cancels outstanding children on close instead of marking them interrupted.
- **B -- drain can extend shutdown.** A one-shot/interactive exit waits for outstanding children;
  they are bounded by the iteration budget and the provider timeout, but not by a separate limit.

**Deferred (C)**

- A dedicated out-of-turn delivery event, a persistent task registry with interrupted marking,
  `/stop`, follow-up instructions, and a background concurrency bound.

## Alternatives considered

- **Emit only.** Rejected after checking the transports: `CliTransport.deliver` only terminates a
  line (text is streamed as deltas) and `WebSocketTransport.deliver` only resolves a pending
  request, so a background result would be invisible to CLI and to connected workbench streams.
- **Publish deltas only.** Rejected: Telegram is not subscribed to events and would never receive
  the message.
- **A dedicated `SubagentCompleted` event and transport handling.** Deferred: it is the durable
  fix for labeling out-of-turn messages, but it is a larger transport-contract change.
- **Deliver from the delegating turn.** Rejected: it would couple delivery to the caller and lose
  results when the parent turn ends first.
