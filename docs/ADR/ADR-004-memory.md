# ADR-004: Two-Tier Memory with Consolidation and Curation

- Status: Accepted
- Date: 2026-10-05
- Supersedes: —

## Context

Conversations outgrow the model context window, but useful facts must survive far longer than
any single session. A single giant memory file is both fragile (hard to parse, hard to version)
and noisy (raw history mixed with curated meaning). newbot needs memory that is fast in the
moment, reflective over time, and always inspectable and reversible by the operator.

## Decision

Separate memory into tiers with distinct guarantees and a bridge between them.

| Tier | Store | Guarantee |
| --- | --- | --- |
| Near-term | Session history (`sessions/*.jsonl`) | Atomic visibility; compaction checkpoints |
| Bridge | Journal (`memory/journal.jsonl`, cursor-based) | Append under lock; atomic on rewrite |
| Long-term | Durable files (`persona.md`, `user.md`, `memory/knowledge.md`) | Curated, versioned, restorable |

- **Consolidation.** When a session is compacted (size, idle timeout, or explicit command), the
  covered turns are summarized and appended to the journal with a monotonic cursor. The model
  continues from the summary; original turns stay in saved history.
- **Curation.** A scheduled, lower-frequency job reads new journal entries plus the current
  durable files and makes the smallest coherent edits to the durable files. It is interpretive,
  not a rewrite.
- **Versioning.** Curation writes are recorded through `VersioningPort` so the operator can
  inspect, diff, and restore, and one pass is grouped as a single revertible change-set. The
  default adapter is a file-system vault.
- **Inspection commands.** `newbot curate` reports its change-set; `newbot memory log`,
  `newbot memory restore <version>`, and `newbot memory revert-set <change-set>` expose the
  process.
- **Sanitization.** Journal entries and durable files are bounded and sanitized at write time
  (C7): no raw tool echoes, unbounded metadata, or local paths that teach the model to imitate
  internal markers.

## Consequences

**Positive**

- Short-term replay stays fast; long-term knowledge becomes clearer over time instead of noisier.
- Memory is inert, inspectable plain files; nothing is hidden in a service or a vector store.
- Every automatic change is reversible.

**Negative / accepted costs**

- Two write paths (append journal, edit durable files) and cursors must stay consistent.
- Curation is model-dependent; its guide must be configurable per workspace.

## Alternatives considered

- **Single `HISTORY.md`.** Rejected: fragile to parse, no stable cursors, mixes raw and curated.
- **Vector database as the primary store.** Rejected for this phase: opaque, hard to inspect or
  version; embeddings remain a possible later adapter (see ARCHITECTURE §17).
- **Full rewrite of memory each cycle.** Rejected: loses history and produces large, noisy
  diffs instead of minimal coherent edits.
