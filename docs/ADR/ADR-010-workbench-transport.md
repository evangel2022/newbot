# ADR-010: Workbench Transport Protocol

- Status: Accepted
- Date: 2026-10-05
- Supersedes: —

## Context

Phase 4 adds a local web workbench. ARCHITECTURE §17 left the wire protocol open: it must be
fixed before code, because transports are long-lived contracts and a client built against a
guessed shape is expensive to change. Two constraints from §3.5/§3.3 shape it:

- an older client and a newer server must keep working (unknown optional capabilities must not
  break either side);
- an unauthenticated peer must not be able to mutate runtime state (S5).

The transport binds to loopback only; exposing the host publicly is out of scope until a full
access-control design exists.

## Decision

The workbench is one loopback HTTP surface, transport id `webui`, versioned by an integer
protocol number.

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| `GET` | `/health` | none | Liveness probe; returns `{"status": "ok"}`. |
| `GET` | `/capabilities` | none | Negotiation: protocol version and capability names. |
| `POST` | `/messages` | bearer token | Submit one turn; reply is the assistant text. |

- **Versioning.** `protocol` is a monotonically increasing integer, currently `1`. A request
  whose `protocol` is not the server's is rejected with `400`; a client may omit it to accept
  the server default.
- **Capabilities.** A capability is a lowercase string. The client sends the capabilities it
  uses; the server ignores names it does not know, so a newer client cannot break an older
  server and vice versa. The server advertises only capabilities it actually implements, so a
  client never waits on a feature the server will not honor.
- **Authentication.** Every mutating request carries `Authorization: Bearer <token>`, where the
  token is `server.token` (an `${ENV}` reference in practice). A missing or wrong token is
  `401`, and no submission is attempted. When `server.token` is unset the workbench refuses all
  mutations (`403`): fail closed, never run unauthenticated.
- **Submission.** `POST /messages` takes `{"conversation": str, "text": str}`; the server submits
  one `InboundEnvelope` for the `webui` transport and returns `{"reply": str}` once the turn
  completes. There is no streaming yet; a client that wants deltas waits for a later capability.
- **Errors.** Failures return a JSON object `{"error": str}` with a non-2xx status; bodies are
  never HTML and never include tracebacks.
- **Assets.** Any client files the workbench serves come from the local installation. A remote
  host supplies data only and can never replace an executable asset (R3).

## Consequences

**Positive**

- The contract is small and additive: new capabilities extend the `capabilities` list without
  changing existing routes.
- Mutations are gated by one check with one owner (`policy/access.py`), not per-route logic.
- The protocol is transport-shaped, so a WebSocket upgrade (streaming deltas) can be added as a
  new capability without a breaking change.

**Negative / accepted costs**

- Request/response submission is not streaming, so the first client waits for the full reply.
- Server and client must both tolerate unknown capability names; neither may assume the other
  understands a capability just because it was negotiated.

## Alternatives considered

- **WebSocket-only workbench.** Rejected for the first slice: capability negotiation and a
  health probe need plain HTTP, so an HTTP surface exists regardless; a synchronous POST proves
  the same transport wiring without a framing protocol.
- **Version per route.** Rejected: one protocol integer with additive capabilities is simpler to
  reason about and to keep compatible.
- **Secret in the URL / query string.** Rejected: tokens belong in the `Authorization` header so
  they do not land in access logs or browser history.
