# ADR-005: Session Identity, JSONL Storage, and Compaction

- Status: Accepted
- Date: 2026-10-05
- Supersedes: —

## Context

Each independent conversation needs its own replayed history, but history grows without bound
and may be accessed concurrently by multiple transports on one host. Session data is sensitive
(it can contain secrets and paths) and must not be reachable by filesystem tools. The store must
be readable with ordinary tools and survive restarts.

## Decision

- **Identity.** A session key derives from the transport plus conversation identity (channel +
  chat/thread, or a workbench chat id). An optional *unified session* mode shares one session
  across transports for single-user multi-device use; it is off by default.
- **Scope.** A session carries an opaque workspace id and an effective project path. Session
  files live under `<config-dir>/sessions/<workspace-id>/`, outside the agent-accessible
  workspace, so tool containment cannot reach them.
- **Log format.** Append-only JSONL. Each record is normalized at the store edge (A4) into a
  typed record: type (user/assistant/tool/system/checkpoint), timestamp, and payload.
- **Compaction.** A checkpoint record marks the boundary: records before it are represented by
  a summary; records after it replay verbatim. Compaction triggers on size threshold, idle
  timeout, or an explicit command, and its summary feeds memory consolidation (ADR-004).
- **Durability.** Writes are atomic (temp + replace); the live file is never truncated in place.
  Crash durability (fsync) is requested only on explicit flush and durable-shutdown paths.
- **Lifecycle.** Sessions persist across restarts. Deleting a session stops and removes its
  subagents; forking a session does not copy subagents.

## Consequences

**Positive**

- One append-only format is easy to stream, tail, migrate, and inspect.
- Checkpoints bound context size without destroying saved history.
- External session storage keeps sensitive history outside the workspace guard's subject path.

**Negative / accepted costs**

- Atomic replacement and cursors add store complexity; locks are required per session.
- Ordinary appends trade crash durability for latency; this trade is deliberate and localized.

## Alternatives considered

- **One database for sessions.** Rejected: opaque, harder to inspect/backup, unnecessary for
  local-first single-host use.
- **In-place truncation on compaction.** Rejected: risks partial loss on crash; atomic replacement
  preserves visibility and recoverability.
- **Storing sessions inside the workspace.** Rejected: exposes sensitive history to filesystem
  tools and complicates containment.