# newbot Roadmap

Status: Phase 1 (design) complete; implementation not started.

This roadmap sequences implementation so that the architecture in
[ARCHITECTURE.md](./ARCHITECTURE.md) is built from the inside out: pure core first, boundaries
next, then the edges. Each phase has an explicit goal, deliverables, and exit criteria. A phase
does not begin until the previous phase's exit criteria are met, because later phases depend on
the contracts earlier phases fix.

Guiding constraints:

- No phase copies another project's code, package names, or internal paths.
- Every phase respects the dependency rule `domain ← ports ← core ← adapters ← app ← cli`.
- Extend at the edges: a capability that can live in a tool/transport/provider/extension never
  enters the core (ADR-001, ADR-008).

---

## Phase 0 — Architecture and Design (done)

- **Goal:** Fix the boundaries, models, and decisions before writing code.
- **Deliverables:** `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, `docs/ADR/ADR-001..009`.
- **Exit criteria:** principles, module boundaries, and per-module contracts are documented and
  internally consistent; no business code written.

## Phase 1 — Foundation and One-Shot Turn

- **Goal:** A working one-shot turn over a single provider and the terminal, with no tools,
  no sessions, and no memory — proving the core split works.
- **Deliverables:**
  - `domain/` value types and typed errors.
  - `ports/` interfaces needed now: `ProviderPort`, `EventSink`.
  - `config/` schema, loader, `${VAR}` resolution, path helpers.
  - `core/hub`, `core/turn`, `core/reasoning`, `core/context` (minimal).
  - `adapters/providers/openai_compatible.py` and a provider registry.
  - `adapters/transports/cli.py`; `app/bootstrap.py`, `app/lifecycle.py`; `cli/entry.py`.
  - `newbot run -m "..."` works end to end with streaming.
- **Exit criteria:**
  - `newbot run -m "hello"` streams a reply from a configured provider.
  - Core is unit-tested against fake provider/transport ports; no adapter import in `core`.
  - Invalid config fails fast with a located error; a missing `${VAR}` is reported.
- **Non-goals:** tools, sessions, memory, scheduler, web workbench, chat connectors.

## Phase 2 — Tools and Security Boundaries

- **Goal:** Give the model safe, guarded capabilities.
- **Deliverables:**
  - `tools/base.py`, `tools/registry.py`, allowlist filtering.
  - `policy/workspace.py`, `policy/network.py`, `policy/redaction.py`.
  - Built-in tools: filesystem (`read`, `write`, `edit`, `list`, patch), shell, web
    (fetch/search).
  - `policy/sandbox.py` with at least one OS backend and fail-closed behavior.
  - Tool-result bounding and sanitization before model context.
- **Exit criteria:**
  - Filesystem tools reject traversal and out-of-workspace paths on every entry point.
  - Web tools block loopback/private/metadata targets; only an explicit whitelist opens a hole.
  - A configured-but-unavailable shell sandbox fails closed rather than running unisolated.
  - Boundary tests exist for traversal, private URL, and shell escape.
- **Non-goals:** MCP, scheduling, delegation, memory.

## Phase 3 — Sessions and Memory

- **Goal:** Persist conversation history and keep durable, inspectable long-term memory.
- **Deliverables:**
  - `session/manager.py`, `session/store.py` (JSONL), `session/compaction.py`.
  - `memory/layout.py`, `memory/journal.py`, `memory/consolidator.py`, `memory/curator.py`.
  - `adapters/stores/jsonl_sessions.py`, `file_memory.py`, `fs_vault.py`.
  - `VersioningPort` + FS-backed vault; inspection commands.
  - Context assembly reads recent messages + memory summary with bounded sizes.
- **Exit criteria:**
  - Interactive terminal sessions persist across restart; compaction checkpoints replay a
    summary plus subsequent messages verbatim.
  - Consolidation appends cursor-based journal entries under a lock; atomic rewrite path exists.
  - Curation edits durable files minimally and every write is inspectable and restorable.
  - Session files live outside the workspace guard's subject path.
- **Non-goals:** multi-transport sharing, unified session mode, RAG/embeddings.

## Phase 4 — Host, Workbench, and Scheduling

- **Goal:** A long-running host serving multiple transports plus scheduled work.
- **Deliverables:**
  - `adapters/transports/http_ws.py` with access control and local client assets.
  - At least one chat connector under `adapters/transports/connectors/`.
  - `app/scheduler.py`: timers, heartbeat tasks, session-bound triggers.
  - `newbot serve` with a health endpoint; `newbot` interactive; `newbot init`.
  - Per-session serialization and bounded cross-session parallelism.
- **Exit criteria:**
  - The workbench negotiates its protocol/capabilities; unknown optional capabilities do not
    break older peers; unconfirmed peers cannot mutate (ADR-007, §3.5).
  - Local client assets are always served locally and never replaced by a remote host.
  - A scheduled turn delivers to its origin session; an at-least-once trigger is deduplicated by
    consumers and a failed delivery is marked failed, not retried forever.
- **Non-goals:** plugins, MCP, delegation.

## Phase 5 — Extensions and Delegation

- **Goal:** Grow capability without touching the core.
- **Deliverables:**
  - `extensions/skills.py`, `extensions/plugins.py`, `extensions/discovery.py`.
  - `tools/mcp.py` with composition-root-owned connect/close lifecycle.
  - `tools/schedule.py`, `tools/delegate.py`, `tools/self.py`.
  - `core/delegation.py` (subagents) with cancel/message/wait and restart recovery.
  - Entry-point tool discovery; provider/transport descriptors.
- **Exit criteria:**
  - A skill, plugin, and MCP server can each be added without modifying `core/`.
  - Subagents run with isolated context, report to their origin session, and mark interrupted
    children with partial results on restart; cancelling one child leaves siblings running.
  - Extension enablement is traceable from config to the concrete implementation.
- **Non-goals:** distributed execution, remote-code hosting, multi-tenant control plane.

---

## Cross-cutting workstreams

These run continuously, not as a phase:

- **Security review** on every path touching filesystem, shell, network, or transport access
  (ADR-007). A new capability must route through the relevant guard.
- **Documentation** updates to `ARCHITECTURE.md` and a new ADR whenever a boundary or public
  contract changes.
- **Verification discipline**: choose checks by changed surface, reuse valid evidence, keep raw
  artifacts out of tracked source (ADR-009).

## Explicitly deferred

- Embeddings/RAG memory adapter (ARCHITECTURE §17).
- Collaborative multi-agent topologies beyond parent/child delegation.
- Horizontal scale-out of the core across hosts.
- Additional OS sandbox backends beyond the first implemented one.