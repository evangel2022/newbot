# ADR-020: Telegram Chat Channel

- Status: Accepted
- Date: 2026-10-05
- Supersedes: none

## Context

`docs/architecture.md` lists chat connectors as transports and Phase 4 requires "at least one chat
connector under `adapters/transports/connectors/`"; newbot had none, so the behavior matrix records
every chat channel as **C -- not implemented**. nanobot's contract (`configuration.md`, `chat-apps.md`)
is `channels.<name>.enabled` plus channel credentials, a channel message that maps to a session, and
a reply that returns to the same chat; nanobot ships Telegram, Discord, and Slack, and adds pairing
and `channels.*.allowFrom` for access control.

## Decision

One channel, Telegram, implemented as a transport adapter that reuses the hub and turn engine.

- Configuration adds `[channels.telegram]`: `enabled` (default `false`), `token` (required when
  enabled), `apiBase` (default `https://api.telegram.org`, overridable for tests and self-hosted Bot
  API servers), `allowedChatIds` (default empty), and `pollTimeoutSeconds` (default `30`).
  `ChannelsSettings` holds the per-channel sections so later channels extend the same shape.
- `adapters/transports/connectors/telegram.py` owns the channel. `parse_update` validates one raw
  update at the boundary with pydantic (`extra="ignore"`, because Telegram keeps adding fields): only
  a non-empty text message from an allowed chat becomes an `InboundEnvelope`, and the conversation id
  is the chat id, so each chat is its own session. A non-empty `allowedChatIds` rejects every other
  chat; an empty list accepts any chat.
- `TelegramConnector.run(submit)` long-polls `getUpdates`. Before polling it confirms the pending
  backlog once, without running turns, so a restart never replays old chat into the agent. Within a
  run the cursor advances per update, and a malformed update is a loud `TransportError` for the batch
  rather than a guess. A deliberate transport failure is warned and retried after one second; a failed
  turn is warned and polling continues. Neither is fatal to the host.
- `TelegramConnector.deliver` sends `sendMessage` for the reply's chat id, which must match a chat-id
  pattern (`-?\d{1,20}`); a response that is not a message id is a `TransportError`.
- `run_serve` builds the channel only when enabled, registers it as a transport, runs it as a task,
  and cancels and closes it during shutdown.
- The bot token joins `configured_secrets`, so it is redacted from tool output and the journal, and
  request errors redact it before they reach stderr, because the Telegram URL embeds the token.

## Consequences

**Positive**

- newbot gains a real chat surface; the reply path reuses the hub and turn engine, so per-session
  serialization and the cross-session concurrency bound apply unchanged.
- Both directions are validated at the boundary: inbound updates become typed envelopes or are
  ignored, and outbound replies must resolve to a numeric chat id.
- The token lives in configuration only and is redacted from every path that could echo it.

**Negative / accepted costs (deliberate differences, B)**

- **B -- allowlist instead of pairing.** nanobot pairs devices and filters with
  `channels.*.allowFrom`; newbot accepts any chat unless `allowedChatIds` is set. Pairing remains
  **C -- not implemented**.
- **B -- text messages only.** Photos, voice, captions, and edited messages are ignored; nanobot
  transcribes voice and handles more message types.
- **B -- no chat commands.** Every text message is a turn; nanobot handles `/new`, `/compact`, and
  friends inside the channel.
- **B -- no multi-channel or chunked delivery.** Telegram is the only channel, and a reply longer
  than Telegram's 4096-character limit fails the delivery rather than being split; a failed delivery
  is terminal (ADR-017).
- **B -- in-memory cursor with a drained backlog.** Messages that arrive while the host is down are
  confirmed and skipped instead of replayed; the offset is not persisted.

## Alternatives considered

- **Webhook intake instead of long polling.** Rejected: it needs a public ingress and a shared
  secret, while newbot's host is loopback-first; polling keeps the channel outbound-only.
- **A generic channel abstraction up front.** Rejected (ADR-008): one channel exists, and
  `parse_update` plus `TransportPort` are the only seams a second channel would need.
- **Persisting the update cursor.** Deferred: draining the backlog at startup already prevents
  replay, and a durable cursor is only needed if a host must be exactly-once across restarts.
- **Replaying the backlog through the agent.** Rejected: a restart would suddenly run a burst of old
  chat through the model; confirming and skipping is the safer default.
- **A dedicated test-only client seam.** Rejected: `apiBase` already covers tests and local Bot API
  servers, so no extra injection point is needed.
