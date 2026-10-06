# ADR-013: Workbench Browser Authentication

- Status: Accepted
- Date: 2026-10-05
- Supersedes: none

## Context

ADR-011 requires `Authorization: Bearer <token>` on the `/stream` WebSocket upgrade, and its own
Context notes the contradiction: "a browser's WebSocket API cannot set an `Authorization` header
on a connection it opens". The workbench's target client is a browser (ADR-010,
`docs/architecture.md` §16.14), so `chat` (HTTP `POST /messages`) was usable from a browser but
`stream` was not. nanobot's documented WebSocket channel serves browser clients by issuing
short-lived tokens (`tokenIssueSecret`) and accepting a token in the connection URL.

ADR-011 also rejects putting the long-lived `server.token` in a URL ("it would leak into access
logs and browser history"). A browser-compatible mechanism must therefore avoid exposing the
long-lived secret while still being possible from `new WebSocket(...)`.

## Decision

The workbench adds a `ticket` capability: a short-lived, single-use credential minted over the
authenticated HTTP surface and presented on the WebSocket upgrade.

- `POST /ticket` requires the existing `Authorization: Bearer <server.token>` check
  (`policy/access.py`). It returns `{"ticket": str, "expiresInSeconds": int}`; the ticket is 256
  bits from `secrets.token_urlsafe`.
- Tickets live only in the transport's memory, expire after 30 seconds, and are consumed on first
  use. The transport owns this ephemeral state; `AccessPolicy` stays stateless and still owns the
  long-lived-token check.
- `GET /stream` accepts the ticket as a WebSocket **subprotocol** named
  `newbot.ticket.<ticket>`, which a browser can set (`new WebSocket(url, [name])`). The server
  echoes the selected subprotocol on the `101` response and consumes the ticket before any frame
  is read. When no ticket subprotocol is offered, the existing `Authorization` header path applies
  unchanged, and the long-lived token is never accepted in the URL.
- `capabilities` advertises `ticket`. An invalid, expired, or reused ticket is `401`; an unset
  `server.token` is still `403` (fail closed).

## Consequences

**Positive**

- The streaming capability is usable from its documented target client without exposing the
  long-lived token to URLs, access logs, or browser history.
- Additive: a client that does not use `ticket` sees exactly the ADR-010/ADR-011 protocol.
- The credential is short-lived and single-use even if it appears in a header log.

**Negative / accepted costs**

- The transport holds small mutable ticket state and prunes it; a ticket that is minted but never
  used expires on the next mint or consume.
- A client must mint a ticket per connection, so reconnecting after a failed upgrade needs a new
  one.
- The subprotocol header is visible to any intermediary; on a loopback-only surface there is
  none, and the credential is short-lived and single-use.

## Alternatives considered

- **Long-lived token in the URL (`?token=`), as nanobot documents.** Rejected: it exposes the
  long-lived secret to logs and history, contradicting ADR-011.
- **Long-lived token as the subprotocol value.** Rejected: it reuses the long-lived secret as a
  per-connection credential; a short-lived ticket limits exposure.
- **Query-parameter ticket.** Rejected in favour of the subprotocol header: it keeps the
  credential out of the URL, and the header is visible only to intermediaries, not to page-URL
  logs.
- **Cookie set by an authenticated HTTP call.** Rejected: adds cookie and CSRF handling for no
  benefit over a single-use ticket.
