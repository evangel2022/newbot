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
- **Status:** config-declared scheduled turns run in `serve` and are recorded to their bound
  conversation (ADR-014, `tests/integration/test_serve.py`); cross-session turn concurrency can
  be bounded with `agent.maxConcurrentTurns` (ADR-015, `tests/unit/core/test_turn.py`); the
  workbench serves a bundled local client at `GET /` (ADR-016,
  `tests/integration/test_workbench.py`); a failed outbound delivery is a terminal `TurnFailed`
  (ADR-017, `tests/unit/core/test_turn.py`); local triggers are queued by `newbot trigger` and
  delivered at-least-once with per-delivery dedup and terminal failed marking (ADR-018,
  `tests/integration/test_triggers.py`); a config-declared heartbeat runs `HEARTBEAT.md` active
  tasks quietly in its own conversation without notifying anyone (ADR-019,
  `tests/integration/test_serve.py`); a Telegram chat channel long-polls messages into per-chat
  sessions and replies in-chat (ADR-020, `tests/integration/test_telegram.py`); the agent can
  create session-bound scheduled jobs through the `cron` tool, dispatched by a `serve` poller
  that advances the registry before each run (ADR-021, `tests/integration/test_cron.py`);
  `newbot status` prints the resolved configuration (path, workspace, provider/model, tool
  policy) without constructing a provider or calling the model
  (`tests/unit/app/test_status.py`); the remaining chat channels are not implemented yet.
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
- **Status:** stdio MCP servers are configured under `[tools.mcp.servers.<name>]`,
  connected at startup, and their tools are exposed to the model as
  `mcp__<server>__<tool>` (ADR-022, `tests/integration/test_mcp.py`); workspace skills
  under `<workspace>/skills/<name>/SKILL.md` are summarized in the system prompt and
  loaded on demand through the `skill` tool (ADR-023,
  `tests/integration/test_skills.py`); HTTP MCP servers are configured with `url` and
  validated and pinned through the SSRF guard on every request (ADR-024,
  `tests/unit/tools/test_mcp_http.py`); a read-only `my` tool reports the run's
  non-secret configuration (ADR-025, `tests/unit/tools/test_my_tool.py`); third-party tools are
  discovered from the `newbot.tools` entry-point group, validated at the boundary, and
  registered subject to the allowlist (ADR-026, `tests/unit/extensions/test_discovery.py`);
  Agent Plugin packages contribute their bundled skills under
  `<workspace>/plugins/<name>/`, activated by `[plugins].enabled` (ADR-027,
  `tests/unit/extensions/test_plugins.py`); a bundled `mcp.json` connects MCP servers with
  contained `PLUGIN_ROOT`/`PLUGIN_DATA` and config precedence (ADR-028,
  `tests/e2e/test_cli_smoke.py::test_cli_calls_a_tool_on_a_plugin_bundled_mcp_server`);
  delegation runs a child turn in-process through the `delegate` tool and returns its reply
  (ADR-029, `tests/unit/core/test_subagents.py`); background tasks can be started, checked,
  waited on, and cancelled, with cancelling one child leaving siblings running (ADR-031);
  a background task's reply is delivered to the origin conversation (ADR-032); running tasks
  are persisted and marked interrupted on restart, keeping their partial reply (ADR-033,
  `tests/unit/adapters/test_subagent_task_store.py`); `/stop` cancels the current session's
  running child tasks and `agent.maxConcurrentTurns` bounds them (ADR-034); the runtime's
  inbound handler routes `/stop` and `/help`, and `/new` resets the conversation (ADR-035,
  ADR-036); the built-in
  `web_search` tool queries DuckDuckGo
  through the SSRF guard and is gated with `web_fetch` by `[tools.web].enable` (ADR-030,
  `tests/unit/tools/test_duckduckgo_search.py`).
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