# ADR-012: Bounded Workbench Request Bodies

- Status: Accepted
- Date: 2026-10-05
- Supersedes: none

## Context

ADR-010 fixed the workbench HTTP surface (`POST /messages`) but left the request body unbounded:
the handler trusted `Content-Length` and read that many bytes into memory. The WebSocket
capability (ADR-011) already bounds every inbound frame (`MAX_MESSAGE_BYTES`, 1 MiB), so a
hostile peer is rejected at the wire boundary there; the HTTP path had no equivalent. Both carry
the same payload shape (`{"conversation", "text", ...}`), so one limit should cover both.

An unbounded body is unvalidated dynamic input at a boundary whose peer is not fully trusted,
and it is a memory-exhaustion path on the loopback surface (ADR-007).

## Decision

`POST /messages` bounds the request body at `MAX_MESSAGE_BYTES` (1 MiB), the same limit the
WebSocket capability applies to an inbound frame.

- A `Content-Length` greater than the limit is rejected with `413` and
  `{"error": "request body too large"}` before the body is parsed and before any turn is
  submitted.
- The server drains a bounded prefix (`MAX_MESSAGE_BYTES + 1`) so a cooperating client receives
  the rejection instead of a connection reset, and never buffers the whole advertised body; the
  connection is then closed.
- A missing, non-numeric, or negative `Content-Length` keeps the existing `400`
  (`invalid Content-Length`), and every failure stays JSON without a traceback (ADR-010).

## Consequences

**Positive**

- Oversized input is rejected at the boundary, consistent with the WebSocket capability and
  ADR-007's "reject at the boundary" principle.
- Memory use per request is bounded regardless of the advertised length.

**Negative / accepted costs**

- A body larger than 1 MiB cannot be submitted; a `POST /messages` request must stay within the
  same limit that already applies to streamed messages.
- A client that advertises a body far larger than the limit may still see a reset after the
  server drains its bounded prefix; only the rejection contract for cooperating clients is
  guaranteed.

## Alternatives considered

- **Read the whole advertised body, then validate.** Rejected: unbounded memory at a boundary
  whose peer is not fully trusted.
- **A separate HTTP limit distinct from the WebSocket limit.** Rejected: they bound the same
  request shape, so two numbers would drift without a reason.
- **Respond and close without draining.** Rejected: the client loses the `413` to a TCP reset.
