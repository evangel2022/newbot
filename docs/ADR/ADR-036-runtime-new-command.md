# ADR-036: `/new` and Unified Command Replies

- Status: Accepted
- Date: 2026-10-06
- Supersedes: none

## Context

ADR-035 routed `/stop` and `/help` in the runtime, but the interactive CLI kept its own `/stop`
output path, and the reference lists `/new` ("Stop current task and start a new conversation") as
the first in-chat command. newbot had no way to reset a conversation's history: the session
service could record and read, but not clear.

## Decision

Add `/new`, make command resolution shared, and give the session service a reset.

- `SessionServicePort.reset(key)` and `SessionManager.reset` replace a session's records with an
  empty history (an atomic store rewrite), leaving memory and other sessions untouched.
- `CommandRouter.reply(envelope) -> str | None` is the pure command resolver; `handle` emits the
  reply to the origin transport, and the interactive CLI calls `reply` and writes it to its prompt
  stream. The CLI's separate `/stop` branch is removed, so there is one command implementation.
- `/new` cancels the conversation's running subagent tasks and resets its history, so it both
  stops current work and starts the conversation over.
- `Runtime` exposes `commands`; `/help` lists `/new`, `/stop`, and the CLI's own commands.

## Consequences

**Positive**

- `/new` and `/stop` behave the same in the terminal, chat, and workbench surfaces, and there is a
  single resolver to extend.
- Resetting is a store rewrite, so it is atomic and never leaves a half-cleared session.

**Negative / accepted costs (deliberate differences, B)**

- **B -- clear in place.** `/new` clears the current session key's history; it does not mint a new
  conversation id, because the chat transport owns that identity.
- **B -- no in-flight cancellation.** `/new` cancels subagent tasks and clears history, but an
  in-flight parent turn is not cancellable yet, so a long turn keeps running to its budget.
- **B -- partial command set.** `/compact`, `/curate`, `/status`, `/model`, and the skill/dream
  commands are still interactive-CLI-only or unimplemented.

**Deferred (C)**

- The remaining chat commands, follow-up instructions to a running child, and a dedicated
  out-of-turn delivery event.

## Alternatives considered

- **A new session id per `/new`.** Rejected: the transport sets the conversation id (a chat id),
  so a client-side rename would break delivery and history lookup.
- **Delete the session file.** Rejected: `rewrite(..., ())` goes through the store port and keeps
  the workspace id and locking consistent.
- **Duplicate `/new` in the CLI and the router.** Rejected: it recreates the `/stop` duplication
  ADR-035 accepted only as a stopgap.
