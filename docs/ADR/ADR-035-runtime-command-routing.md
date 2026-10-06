# ADR-035: Runtime Command Routing

- Status: Accepted
- Date: 2026-10-06
- Supersedes: none

## Context

ADR-034 wired `/stop` only into the interactive CLI. The reference treats `/stop` and `/help` as
commands available in the chat surfaces too, and `AGENTS.md` says execution and policy stay in
the runtime, not in the WebUI/TUI clients. newbot had no place to handle a command that arrives
as an ordinary inbound message from a chat or workbench transport: `TurnEngine.handle` was bound
directly to the hub's inbound handler.

## Decision

Intercept known commands between the hub and the turn engine.

- `app/commands.py` adds `CommandRouter`, which becomes the hub's inbound handler. A trimmed
  message that equals a known command is handled in the runtime and its reply is delivered with
  `hub.emit` to the origin transport; every other message is delegated to `TurnEngine.handle`.
- The command set is `/stop` (cancel this conversation's running subagent tasks) and `/help`.
  An unknown `/x` is **not** intercepted: it runs a turn, so a leading slash is never silently
  swallowed.
- Commands are handled for every transport, so a Telegram or workbench client gets `/stop`
  without any client-side logic. A command with `reply=False` is handled but not delivered,
  matching runtime-originated work.
- `app/bootstrap.py` binds `router.handle` instead of `engine.handle`. The interactive CLI keeps
  its own `/stop` (it writes straight to the prompt and also serves `/compact`/`/curate`), and
  its command lines never reach the hub.

## Consequences

**Positive**

- `/stop` and `/help` work in chat and workbench surfaces, and the clients stay thin.
- The reply path is the normal outbound envelope, so any message transport delivers it.
- Unrecognized slashes still reach the model, so a user cannot lose a message to a typo.

**Negative / accepted costs (deliberate differences, B)**

- **B -- two `/stop` paths.** The interactive CLI writes the reply itself while chat transports
  go through the router; they share `SubagentManager.cancel_session` but not the output code.
- **B -- a small command set.** Only `/stop` and `/help` are routed; `/new`, `/compact`, and
  `/curate` (which need session/provider wiring) are deferred.

**Deferred (C)**

- The remaining chat commands, follow-up instructions to a running child, and a dedicated
  out-of-turn delivery event.

## Alternatives considered

- **Handle commands in each connector.** Rejected by `AGENTS.md`: it puts policy in the clients
  and duplicates it per channel.
- **Handle commands inside `TurnEngine`.** Rejected: the engine would need to know the command
  set and the subagent manager, expanding the core's surface for a routing concern.
- **Intercept every leading `/`.** Rejected: it would swallow model-directed messages that merely
  start with a slash.
