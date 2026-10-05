# ADR-011: Workbench Streaming Capability

- Status: Accepted
- Date: 2026-10-05
- Supersedes: —

## Context

ADR-010 fixed the workbench request/response surface and left streaming out: `POST /messages`
returns only the final reply, so a client cannot render assistant text as it is produced. The
`ResponseDelta` event already exists and reaches local subscribers, so the capability is
available; only the wire format is open. `docs/architecture.md` (§4, §16.14) names the workbench
as "HTTP + WebSocket" and gives the transport adapter ownership of its wire protocol.

Two constraints carry over from ADR-010 and S5:

- one loopback surface on `server.port`: a second port would widen the exposure and split access
  control;
- an unauthenticated peer must not mutate runtime state, and a browser's WebSocket API cannot set
  an `Authorization` header on a connection it opens.

## Decision

Streaming is a new capability, `stream`, on the same loopback surface and port. `GET /stream` is
upgraded to a WebSocket (RFC 6455) instead of being answered with HTTP.

- **Authentication.** The upgrade request carries `Authorization: Bearer <token>`, checked by the
  same `policy/access.py` owner as `POST /messages`: missing or wrong is `401`, and an unset
  `server.token` is `403` (fail closed). The connection is authenticated before any frame is
  read, so no unauthenticated turn can be submitted. The token is never placed in the URL, where
  it would leak into access logs and browser history.
- **Framing.** Server-side RFC 6455 only as far as the workbench needs: text messages, inbound
  frames must be masked, control frames are answered (`ping` to `pong`, `close` to `close`), and
  every message is bounded. Extensions, subprotocols, and compression are never negotiated. The
  framing lives in `adapters/transports/websocket.py`; the adapter owns its wire protocol
  (§16.14) and no third-party dependency is added.
- **Conversation.** `GET /stream?conversation=<id>` binds the connection to one conversation
  (default `default`), so streamed events are correlated by session rather than by a request id.
- **Frames.** The client sends one JSON object per text frame, `{"text": str, "protocol": int}`.
  The server replies with one JSON object per text frame: `{"type": "started"}`, then zero or
  more `{"type": "delta", "text": str}`, and exactly one terminal
  `{"type": "done", "status": str}` or `{"type": "error", "message": str}`.
- **Failures.** A malformed or incompatible application frame is answered with an `error` frame
  and the connection stays open so the client can retry; a wire-level violation closes the
  connection with the matching status code (1002 protocol error, 1003 unsupported data, 1009
  message too large). The server never sends a traceback.

## Consequences

**Positive**

- Assistant text reaches the client as it is produced, on the same port and access boundary as
  the existing surface.
- `stream` is additive: a client that does not use it sees exactly the ADR-010 protocol.
- No new runtime dependency; the wire protocol stays owned by the transport adapter. (The
  interop test uses the third-party `websockets` client, declared as a dev-only dependency.)

**Negative / accepted costs**

- The transport carries a deliberately minimal RFC 6455 implementation that must be maintained.
- One connection streams one conversation, and the newest connection for a conversation wins.
- A terminal frame is required; a client that disconnects mid-turn leaves the turn running
  (cancellation is out of scope for this slice).

## Alternatives considered

- **Server-Sent Events on `POST /messages`.** Simpler, but one-directional and a deviation from
  the "HTTP + WebSocket" surface named in `docs/architecture.md`; rejected for consistency with
  the documented transport.
- **A second WebSocket port.** Rejected: it widens the loopback exposure and splits access
  control and capability negotiation across two endpoints.
- **A third-party WebSocket server (`websockets`, Starlette).** Rejected: sharing one port would
  force the HTTP server to adopt the library's listening socket, and the adapter is already
  permitted to own its wire protocol without adding a runtime dependency.
- **Raw deltas with no terminal frame.** Rejected: the client could not distinguish a finished
  turn from a stalled one.
