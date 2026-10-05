# newbot Architecture

Status: Phase 1 design (reverse-analysis + independent design). No implementation code exists yet.

This document is the authoritative design for **newbot**, an independently designed AI agent
runtime. It is derived from this repository's engineering rules (`AGENTS.md`, `.agent/*.md`)
and from an analysis of the *public behavior* of comparable agent runtimes. It does not reuse
any source, package name, module path, or internal identifier from those projects.

Contents:

1. Product Positioning
2. Core Capabilities and Non-Goals
3. Principles (Architecture / Coding / Security / Testing / Review / Workflow)
4. Architecture Overview
5. Module Boundaries
6. Runtime Model
7. Agent Model
8. Tool Model
9. Memory Model
10. Session Model
11. Configuration Model
12. Security Model
13. Extension Model
14. Testing Strategy
15. Directory Structure
16. Module Specifications
17. Open Questions

---

## 1. Product Positioning

**newbot is a self-hosted, provider-agnostic agent runtime.** One small execution core turns
inbound messages into model-driven turns with tool access, durable memory, and scheduled work,
then returns replies over whichever transport the user is on.

- **One runtime, thin clients.** The Python runtime owns execution, sessions, memory, tools,
  and security policy. Terminal, web, and chat-app surfaces are adapters that only translate
  transport; they never own policy or agent execution.
- **Local-first and inspectable.** Config, sessions, and memory live in plain files on the
  operator's machine. State is human-readable and versionable. Nothing important is hidden
  in a service.
- **Provider-agnostic.** Hosted and local model backends are interchangeable behind one
  provider port. Switching providers is configuration, not code.
- **Safe by construction at the edges.** Filesystem, shell, and network capabilities are
  guarded on every path, not only on the "main" one.
- **Extensible without touching the core.** New capability arrives as a tool, transport,
  provider, skill, plugin, or MCP server at the edge; the core path stays minimal.

## 2. Core Capabilities and Non-Goals

### 2.1 Core capabilities

| Capability | Description |
| --- | --- |
| Agent execution | Turn orchestration + a bounded provider/tool reasoning loop with streaming. |
| Providers | Pluggable LLM backends (OpenAI-compatible, Anthropic-style, local servers). |
| Transports | CLI one-shot/interactive, a local web workbench (HTTP + WebSocket), chat connectors. |
| Tools | Filesystem, shell, web fetch/search, MCP, scheduling, delegation, self-inspection. |
| Memory | Near-term session replay + long-term durable knowledge, consolidated over time. |
| Sessions | Per-conversation history, checkpoints/compaction, workspace scoping. |
| Scheduling | Timers, heartbeat tasks, and session-bound external triggers. |
| Delegation | Subagents with isolated context reporting back to their origin session. |
| Extensions | Skills, plugins, MCP servers, entry-point tools, providers, transports. |
| Security policy | Workspace containment, SSRF guarding, optional OS sandbox, transport access control. |

### 2.2 Non-goals

- **Not a hosted multi-tenant SaaS.** No control plane, billing, or per-tenant isolation tiers.
  Isolation is per instance/workspace, not per arbitrary customer.
- **Not a UI product.** newbot ships a workbench, but the UI is an adapter; no design system,
  no proprietary frontend framework.
- **Not a vector-database platform.** Memory is file-based and curated; embeddings/RAG are an
  optional later adapter, not the architecture's center.
- **Not a model training or fine-tuning framework.** newbot consumes models; it does not train.
- **Not a distributed job orchestrator.** One host runs one runtime; horizontal scale-out of
  the core is out of scope.
- **Not a remote-code host.** A remote host supplies authenticated data and events; it never
  supplies executable client assets (see §13).

## 3. Principles

The six principle sets below are the binding rules for newbot. They are adapted from this
repository's engineering rules and must be applied on every affected path.

### 3.1 Architecture Principles

- **A1 — Small core, extend at the edges.** The execution core (`core/turn`, `core/reasoning`)
  is the critical path. Changes there must be minimal and justified. Any capability that can
  live in a transport, tool, skill, plugin, or MCP server must not be inlined into the core.
- **A2 — Dependencies point inward.** `domain` has no dependencies. `ports` depend only on
  `domain`. `core` depends on `domain` and `ports`. `adapters` and `app` depend on all of
  them. The core must never import an adapter.
- **A3 — Explicit over magical.** Configuration lives in typed models. Provider/transport
  selection must be traceable from the composition root to the concrete class; no hidden
  global registries, no import-time side effects that silently add capability.
- **A4 — Type the dynamic boundaries.** Wire payloads, persisted records, and third-party SDK
  objects are untrusted and dynamic. Normalize once at the owning edge into a concrete type.
  Raw dictionaries and SDK objects must not flow into the core.
- **A5 — Prefer duplication over premature abstraction.** Adapters (transports, providers)
  may repeat similar logic (retry, media handling, splitting). Do not build a base-class
  hierarchy across adapters just to remove duplication. Each adapter must be readable alone.
- **A6 — State has one owner.** Every piece of runtime state has exactly one owning module.
  Fan-out happens through events, never by two modules writing the same state.
- **A7 — Fail closed at the boundary, trust inside.** Validate untrusted input once, at its
  edge. Inside a validated path, do not re-check or recover from impossible states.

### 3.2 Coding Principles

- **C1 — Understand before extending.** Establish required behavior, available facts, state
  ownership, and root cause first. Then pick the simplest coherent implementation. Never start
  by asking "where do I add another condition?".
- **C2 — Refactor when the structure is the problem.** Fix the owning path when the cause is
  duplicated state, contradictory ownership, or tangles control flow. A small diff is not a
  success if the defect stays embedded in the design.
- **C3 — No speculative generality.** Do not add fallbacks, mode flags, compatibility shims,
  or frameworks for hypothetical future needs. Keep fallbacks only for supported, reachable
  failure modes with a defined result.
- **C4 — No silent invariant recovery.** Do not swallow broken internal invariants. Preserve
  deliberate security checks and documented recovery contracts.
- **C5 — Concrete types over `Any`.** First-party values are typed where stored or passed.
  Reserve `Any` for genuinely dynamic boundaries. Every cast must be justified by a boundary
  check or an invariant established by construction.
- **C6 — Formatting discipline.** Do not run a blanket formatter; mechanical reformatting
  obscures history and creates unrelated diffs. Match surrounding style; format only what the
  change actually touches, and only when the project enables it.
- **C7 — Bounded context input.** Anything written into memory, session history, or prompt
  input can be replayed to the model. Timestamps, local paths, tool-call echoes, and raw
  fallback dumps must be bounded and sanitized at the write boundary.

### 3.3 Security Principles

- **S1 — One path resolver.** All filesystem path handling resolves through the workspace
  guard and performs an explicit containment check with read/write capability semantics.
- **S2 — Capability-specific extra roots.** Extra directories are opt-in per capability:
  read-only roots, write roots, and exact-file allowlists are distinct. A write root is never
  implied by a read root.
- **S3 — One network guard.** Every outbound HTTP request from a tool passes the shared URL
  guard (loopback, private, link-local, CGNAT, and metadata endpoints blocked). The only
  escape hatch is an explicit, operator-configured whitelist.
- **S4 — Sandbox is opt-in and fail-closed.** OS-level shell isolation is optional. On
  platforms where a configured sandbox cannot start, the command fails rather than running
  unisolated. The application-level workspace guard never substitutes for real isolation.
- **S5 — Transport access control.** Chat/WebSocket transports enforce allowlists, pairing,
  or tokens. An unauthenticated or unconfirmed transport may not authorize mutations.
- **S6 — Secrets stay out of state.** Credentials come from environment references; they are
  never written into the workspace, memory, session history, or prompt context.

### 3.4 Testing Principles

- **T1 — Tests must earn their place.** Prefer evidence for a supported user path and the
  important reachable regression. Reuse existing coverage when it already proves the contract.
- **T2 — No defensive tests for impossible states.** No cases for hypothetical internal
  states, unsupported combinations, or failures without a reachable path and material
  consequence.
- **T3 — Test the real boundaries.** Invalid input where an untrusted boundary accepts it,
  security properties where a real capability exposes them, recovery where the product
  promises it.
- **T4 — Assert contracts, not steps.** Avoid exhaustive mock permutations and assertions
  that mirror private implementation steps.
- **T5 — Reuse evidence with its diff.** Carry verification forward with the intervening
  change and the reason the proved contract is unaffected; do not re-run everything blindly.

### 3.5 Review Principles

- **R1 — Compatibility is a contract, not a version comparison.** Different package versions
  may speak the same protocol. Unknown optional capabilities must not break older peers.
- **R2 — Negotiate, don't assume.** Missing or malformed peer metadata means *compatibility
  unconfirmed*. An unconfirmed core contract cannot authorize mutations.
- **R3 — Local assets stay local.** The local installation owns executable assets. A remote
  host supplies data/events/media only; never replacement code.
- **R4 — Read with the design and security rules.** Review the WebUI/transport checklist
  alongside §3.1 and §3.3, not instead of them.
- **R5 — Report compatibility honestly.** State which side needs updating; never tell a newer
  peer to downgrade; never silently install, restart, or revoke credentials.

### 3.6 Development Workflow

1. **Analyze** — required behavior, state ownership, root cause, owning layer.
2. **Design** — place the change at the correct boundary (core only if unavoidable); update
   the affected ADR/model in this document.
3. **Implement** — smallest coherent change; typed at boundaries; no speculative fallbacks.
4. **Verify** — choose checks by changed surface (§14); reuse prior evidence where valid.
5. **Review** — apply §3.5 and §3.3; confirm the security boundary still holds.
6. **Document** — update this file and the relevant ADR when a boundary or contract changes.

## 4. Architecture Overview

newbot is a hexagonal (ports-and-adapters) system with one small execution core.

```
        transports (adapters)                     providers (adapters)
   CLI | HTTP/WS | chat connectors            hosted | local | gateway
             │                                          ▲
             │ InboundEnvelope / OutboundEnvelope       │ ProviderPort
             ▼                                          │
   ┌─────────────────────── core ───────────────────────┴─────────┐
   │  EventHub ──► TurnEngine ──► ContextAssembler ──► ReasoningLoop│
   │                   │                                   │       │
   │                   └──────────► ToolRegistry (port) ◄───┘       │
   └───────────────┬───────────────────────────┬───────────────────┘
                   │                           │
          SessionPort / MemoryPort      policy (workspace, network,
                   │                     sandbox, access, redaction)
                   ▼                           │
          adapters/stores                     ▼
      JSONL sessions | file memory     every fs/shell/net tool call
```

**Dependency rule (enforced by review and import lint):**

```
domain  ←  ports  ←  core  ←  adapters  ←  app  ←  cli
                     ▲
                   policy  (used by core and adapters, depends on domain only)
```

- `domain` — pure data types and value objects. No I/O, no framework imports.
- `ports` — interfaces the core requires (`Protocol`/ABC). Depends on `domain` only.
- `core` — turn orchestration, reasoning loop, context assembly, delegation, event hub.
- `policy` — security guards. No knowledge of transports or providers.
- `adapters` — concrete providers, transports, and stores implementing ports.
- `app` — composition root: reads config, constructs adapters, wires the core, owns lifecycle.
- `cli` — argument parsing and process entry; delegates immediately to `app`.

**Reverse-analysis note.** Comparable runtimes succeed because of four structural ideas, which
newbot adopts as *ideas*, not as code: (a) one long-running process owns execution while
multiple thin surfaces share it; (b) a single narrow provider/tool loop is the critical core;
(c) state lives in plain files split into near-term history and long-term memory; (d) safety
is enforced at capability boundaries (paths, network, shell). newbot re-derives each with its
own module boundaries, names, and ownership rules documented below.

## 5. Module Boundaries

| Module | Owns | May depend on | Must never depend on |
| --- | --- | --- | --- |
| `domain` | Core value types, errors | — | everything else |
| `ports` | Interface contracts | `domain` | `core`, `adapters`, `app` |
| `policy` | Security guards | `domain`, stdlib | `core`, `adapters` |
| `core` | Turn/reasoning execution | `domain`, `ports`, `policy` | `adapters`, `app`, `cli` |
| `session` | Session persistence/compaction | `domain`, `ports` | `core`, `adapters` |
| `memory` | Journal, consolidation, curation | `domain`, `ports` | `core`, `adapters` |
| `tools` | Tool contracts + built-in tools | `domain`, `ports`, `policy` | `core`, `adapters`, `app` |
| `config` | Schema, loading, paths | `domain` | `core`, `adapters`, `tools` |
| `adapters.*` | Concrete providers/transports/stores | `domain`, `ports`, `policy`, `config` | `core internals`, `app`, `cli` |
| `extensions` | Skills/plugins/MCP discovery | `domain`, `ports`, `config` | `core internals` |
| `app` | Composition, lifecycle, scheduler | everything | `cli` |
| `cli` | Process entry | `app`, `config` | internals of `core`/`adapters` |

Rules:

- The core talks to the outside world **only** through `ports`.
- Transports never call tools, providers, or stores directly; they translate to/
  from envelopes and use the hub.
- No adapter imports another adapter. Cross-adapter reuse goes through a port or is duplicated
  deliberately (A5).
- `policy` is a leaf utility set: guards take explicit inputs and return decisions; they do not
  read config globals at call time (config is injected once at construction).
- Value types that cross the `ports` boundary (`AgentEvent`, `InboundEnvelope`/
  `OutboundEnvelope`, `SessionKey`, `ModelRequest`/`StreamEvent`) live in `domain`, because
  `ports` must be referenceable by both `core` and adapters without depending on `core` (A2).

## 6. Runtime Model

### 6.1 Process shapes

| Entry | Purpose |
| --- | --- |
| `newbot run -m "..."` | One-shot turn; prints the reply; exits. |
| `newbot` (no args) | Interactive terminal session with persistent history. |
| `newbot serve` | Long-running host: enabled transports + scheduler + curator + health endpoint. |
| `newbot init` | Create config/workspace defaults (never recovers from an invalid file). |

### 6.2 Turn lifecycle

1. A transport receives input and publishes an `InboundEnvelope` to the `EventHub`.
2. `TurnEngine` resolves the session key and workspace scope, and enqueues the turn on the
   session's serial queue (one active turn per session).
3. `ContextAssembler` builds the model request: system/policy prompt, agent persona, project
   instructions, memory summary, and recent session messages.
4. `ReasoningLoop` calls the selected `ProviderPort`; stream deltas are emitted as events.
5. Tool calls are dispatched through the `ToolRegistryPort`; results are validated, bounded,
   and fed back into the loop until a final answer or a budget limit.
6. The turn is persisted to the session; memory consolidation may run; the reply is published
   as an `OutboundEnvelope` to the origin transport.

### 6.3 Concurrency and delivery

- **Per-session serialization.** A session processes one turn at a time; new inbound work is
  queued, not injected into an active turn.
- **Cross-session parallelism** is allowed but bounded by a global worker limit.
- **Event fan-out.** `EventHub.publish` awaits local subscribers for state changes;
  `EventHub.emit` queues routed outbound delivery without awaiting network I/O.
- **Delivery semantics.** Outbound channel delivery is at-least-once; consumers must tolerate
  duplicates. A turn that reaches the agent but fails is marked failed, not retried forever.
- **Durability.** Session writes are atomic (temp + replace). Crash durability (fsync) is
  requested only on paths that require it (explicit flush, durable shutdown); ordinary appends
  trade durability for latency, deliberately and in one place.

## 7. Agent Model

- **Agent definition** is immutable configuration resolved at composition: provider/model,
  tool allowlist, workspace scope, prompt template set, budgets, and policy options.
- **Turn** is one unit of work within a session; it owns an iteration budget (max model↔tool
  round trips), a token/character budget for tool results, and a cancellation token.
- **Context assembly** combines, in a fixed order: platform/runtime policy → agent persona →
  project instructions → memory summary → recent messages → channel metadata. Each block has a
  bounded size; overflow is summarized, not silently truncated mid-sentence.
- **Delegation (subagents).** A subagent is a child session with its own turn and an isolated
  context window. It reports progress/results to its origin session. Cancelling a parent turn
  cancels its children; cancelling one child leaves siblings running. Results persist across
  restart; unfinished children are marked interrupted with partial results retained.
- **State ownership.** The agent's persona/user profile are owned by the agent workspace;
  project instructions and relative tool paths are owned by the selected project workspace.
  Selecting a project changes working context only — it does not create a second agent.

## 8. Tool Model

- **Tool contract.** A tool exposes a stable name, a description, a JSON-schema parameter
  spec, and an async `invoke(args, ctx) -> ToolResult`. Names, schemas, and error messages are
  a model-facing contract and change only intentionally.
- **ToolContext.** Carries the resolved workspace scope, read/write capabilities, policy
  guards, event sink, cancellation token, and the owning session id. Tools receive only what
  they need; they never reach into global state.
- **Registry.** Tools are discovered from built-in modules and explicit entry points, then
  filtered by the agent's allowlist. Discovery is deterministic and traceable; there are no
  import-time side effects that silently enable a tool.
- **Built-in groups.** filesystem (`read`, `write`, `edit`, `list`, patch), shell, web
  (fetch/search), MCP (external servers), schedule (timers/heartbeat/triggers), delegate
  (subagents), and self-inspection (runtime state).
- **Result discipline.** Tool results are bounded in size, sanitized of local paths and
  internal markers, and normalized into `ToolResult` before entering model context.
- **Policy injection.** Filesystem, shell, and web tools call `policy` guards on every path;
  a tool must not perform raw path resolution or raw HTTP (S1–S3).

## 9. Memory Model

Memory has two tiers with different guarantees.

| Tier | Store | Purpose | Guarantee |
| --- | --- | --- | --- |
| Near-term | Session history (`sessions/*.jsonl`) | Replayed conversation turns | Atomic visibility; compaction checkpoints |
| Long-term | Durable files in the agent workspace | Persona, user profile, project knowledge | Curated, versioned, restorable |
| Bridge | Journal (`memory/journal.jsonl`) | Append-only summaries of compacted turns | Append under lock; atomic on rewrite |

**Durable file set** (newbot's own layout):

```
<agent-workspace>/
├── persona.md            # agent voice and communication style
├── user.md               # stable knowledge about the user
└── memory/
    ├── knowledge.md      # durable project facts and decisions
    ├── journal.jsonl     # append-only consolidated summaries (cursor-based)
    └── cursors.json      # consolidation + curation cursors
```

- **Consolidation.** When a session is compacted (size, idle timeout, or explicit command),
  the covered turns are summarized and appended to the journal with a monotonic cursor. The
  model continues from the summary; original turns remain in saved history.
- **Curation.** A scheduled, lower-frequency job reads new journal entries plus the current
  durable files and makes the *smallest coherent edits* to `knowledge.md`/`user.md`/`persona.md`.
  It is interpretive, not a rewrite.
- **Versioning.** Every curation write is recorded so the operator can inspect, diff, and
  restore. A curation pass records its edits as one change-set, so the whole pass can be
  reverted together. Versioning is a port (`VersioningPort`); the default adapter is a
  file-system vault.
- **Inspection commands.** An interactive session accepts `/compact`, `/curate`, `/help`, and
  `/exit`; the same work is available one-shot as `newbot compact`, `newbot curate`,
  `newbot memory log`, `newbot memory restore <version>`, and
  `newbot memory revert-set <change-set>`. Automatic memory must remain inspectable and
  reversible.
- **Context-pollution guard.** Journal entries and durable files are sanitized at write time
  (C7): no raw tool echoes, no unbounded metadata, no local paths that would teach the model to
  imitate internal markers.

## 10. Session Model

- **Session identity.** A session key derives from the transport plus conversation identity
  (channel + chat/thread, or a WebUI chat id). An optional *unified session* mode deliberately
  shares one session across transports for single-user multi-device use; it is off by default.
- **Workspace scope.** A session carries an opaque workspace id and an effective project path.
  Session namespaces live outside the agent-accessible workspace so tool containment cannot
  reach them.
- **Message log.** Append-only records per session. A record has a type (user/assistant/tool/
  system/checkpoint), a timestamp, and a payload. Records are normalized at the store edge (A4).
- **Compaction.** A checkpoint record marks the boundary: messages before it are represented by
  a summary, messages after it replay verbatim. Compaction triggers on size threshold, idle
  timeout, or an explicit command.
- **Storage.** JSONL per session under `<config-dir>/sessions/<workspace-id>/`. Writes are
  atomic; the live file is never truncated in place.
- **Lifecycle.** Sessions persist across restarts. Deleting a session stops and removes its
  subagents; forking a session does not copy subagents.

## 11. Configuration Model

- **Typed schema.** All configuration lives in Pydantic models in `config/schema.py`. Unknown
  keys are rejected or explicitly ignored — never silently coerced.
- **Layering.** Effective config is resolved in order: built-in defaults → config file →
  environment reference expansion (`${VAR}`) → CLI flags. Resolved once at startup into an
  immutable settings object.
- **Fail fast.** A missing referenced environment variable or an invalid file raises a typed
  load error with field locations. The file is read as UTF-8, tolerating a leading BOM; other
  encodings raise a located load error. Defaults are created only when the file is absent; an
  invalid file is never "recovered" from.
- **Key style.** The schema accepts both `camelCase` and `snake_case` on read and writes
  `camelCase` on save, keeping on-disk config stable and unambiguous.
- **Paths.** Two distinct roots: the **config dir** (config, sessions, logs, media, runtime
  data) and the **agent workspace** (persona, user, memory, skills, generated artifacts). Both
  are overridable by CLI flags. A third, per-session **project workspace** may differ from the
  agent workspace.
- **No secrets on disk.** Secrets are `${ENV}` references resolved at load; the loader reports
  unresolved references rather than writing resolved values back.

## 12. Security Model

| Boundary | Rule |
| --- | --- |
| Filesystem paths | All path handling goes through the workspace guard (S1). Containment is checked against the effective project workspace; extra roots are capability-specific (S2). |
| Shell execution | The application guard rejects working directories outside the workspace and blocks obvious escapes. Optional OS sandbox (S4) provides real isolation; a configured-but-unavailable sandbox fails closed. |
| Outbound HTTP | All tool HTTP goes through the shared network guard (S3). Loopback/private/link-local/CGNAT/metadata targets are blocked; only an explicit CIDR whitelist opens a hole. The validated address is pinned for the connection, so a rebinding resolver cannot redirect it after validation, and the response body is read under a size bound. Explicit operator-configured provider proxies are a separate, authorized trust boundary. |
| MCP transports | HTTP/SSE MCP endpoints are validated before probing and before each request; private endpoints require the explicit whitelist. Stdio MCP servers are outside the HTTP guard. |
| Transport access | Chat/WebSocket transports enforce allowlists, pairing, or tokens (S5). Unconfirmed peers cannot mutate. |
| Client/peer assets | The local installation owns executable assets; remote hosts supply data/events/media only (R3). |
| Secrets | Environment references only; never persisted to workspace, memory, or prompts (S6). |
| Context pollution | Persisted memory/prompt inputs are sanitized and bounded (C7). |

Rule: any new capability that touches paths, network, or process execution must route through
the corresponding guard. A new guard backend must match the existing backend contract and
preserve its failure behavior.

## 13. Extension Model

| Extension | How it is added | Boundary |
| --- | --- | --- |
| Provider | Register a spec + implement the provider port | `adapters/providers` |
| Transport | Implement the transport port; export a descriptor | `adapters/transports` |
| Tool | Implement the tool contract under `tools/` or an entry point | `tools` |
| Skill | Markdown + YAML frontmatter under workspace `skills/` or built-ins | `extensions/skills` |
| Plugin | Package bundling skills and/or MCP servers | `extensions/plugins` |
| MCP server | Config entry or bundled in a plugin | `tools/mcp` |
| Scheduler job | Register with the scheduler; workspace-scoped | `app/scheduler` |

Rules: prefer the existing registry/discovery patterns over ad hoc wiring (A3); a capability
that is "know-how" rather than code belongs in a skill, not in the agent loop (A1); plugin/MCP
lifecycle is owned by the composition root, which connects before use and closes on shutdown —
the core never manages connection lifecycle.

## 14. Testing Strategy

Choose verification by changed surface; stop once evidence is sufficient (T1).

| Change | Minimum useful verification |
| --- | --- |
| `domain`/`core` logic | Unit tests with in-memory fake ports; assert turn/reasoning contracts. |
| Provider behavior | Provider unit tests against a mocked API path; one real safe call when possible. |
| Transport behavior | Transport tests plus a host-startup path. |
| WebUI/workbench | Frontend tests/build and browser-level verification through the host. |
| Tool behavior | Tool unit tests plus an agent-run path when the schema changes. |
| Security guard | Boundary tests with real invalid input (traversal, private URL, escape) (T3). |
| Config | Load-error tests for missing env refs and invalid files. |
| Docs | Link checks, command accuracy against schema, whitespace check. |

Layers: `tests/unit` (pure, fast, fakes), `tests/integration` (real store/provider/transport
boundaries), `tests/e2e` (public surfaces: CLI, HTTP/WS, packaged import). Reuse prior
evidence with the intervening diff (T5). Raw verification artifacts stay out of tracked source.

## 15. Directory Structure

```
newbot/
├── AGENTS.md                     # engineering rules (this repo's guide)
├── .agent/                       # detailed rule documents
├── pyproject.toml
├── docs/
│   ├── ARCHITECTURE.md           # this document
│   ├── ROADMAP.md
│   └── ADR/
│       ├── README.md
│       ├── ADR-001-architecture.md
│       ├── ADR-002-agent-runtime.md
│       ├── ADR-003-tool-system.md
│       ├── ADR-004-memory.md
│       ├── ADR-005-session.md
│       ├── ADR-006-configuration.md
│       ├── ADR-007-security.md
│       ├── ADR-008-extension.md
│       └── ADR-009-testing.md
├── src/newbot/
│   ├── __init__.py
│   ├── domain/                   # pure types, no I/O
│   │   ├── message.py            # Message, Role, Envelope
│   │   ├── turn.py               # Turn, TurnStatus, Budget
│   │   ├── session.py            # SessionId, SessionRef, Record
│   │   ├── tool.py               # ToolCall, ToolResult, ToolSpec
│   │   ├── memory.py             # JournalEntry, MemoryCursor
│   │   └── errors.py             # typed errors
│   ├── ports/                    # interface contracts
│   │   ├── provider.py           # ProviderPort
│   │   ├── tools.py              # ToolRegistryPort
│   │   ├── sessions.py           # SessionStorePort
│   │   ├── memory.py             # MemoryStorePort
│   │   ├── transports.py         # TransportPort
│   │   ├── events.py             # EventSink
│   │   ├── scheduler.py          # SchedulerPort
│   │   └── versioning.py         # VersioningPort
│   ├── policy/                   # security guards (leaf)
│   │   ├── workspace.py          # path resolution + containment
│   │   ├── network.py            # SSRF/URL guard
│   │   ├── sandbox.py            # shell sandbox backends
│   │   ├── access.py             # transport access control
│   │   └── redaction.py          # secret/context sanitization
│   ├── core/                     # execution core
│   │   ├── hub.py                # EventHub + envelopes
│   │   ├── turn.py               # TurnEngine
│   │   ├── reasoning.py          # ReasoningLoop
│   │   ├── context.py            # ContextAssembler
│   │   ├── delegation.py         # SubagentManager
│   │   ├── budget.py
│   │   └── events.py             # AgentEvent types
│   ├── session/                  # session subsystem
│   │   ├── manager.py
│   │   ├── store.py              # JSONL store
│   │   └── compaction.py
│   ├── memory/                   # memory subsystem
│   │   ├── layout.py
│   │   ├── journal.py
│   │   ├── consolidator.py
│   │   └── curator.py
│   ├── tools/                    # tool contracts + built-ins
│   │   ├── base.py
│   │   ├── registry.py
│   │   ├── filesystem.py
│   │   ├── shell.py
│   │   ├── web.py
│   │   ├── mcp.py
│   │   ├── schedule.py
│   │   ├── delegate.py
│   │   └── self.py
│   ├── config/
│   │   ├── schema.py
│   │   ├── loader.py
│   │   └── paths.py
│   ├── adapters/
│   │   ├── providers/
│   │   │   ├── registry.py
│   │   │   ├── openai_compatible.py
│   │   │   ├── anthropic_style.py
│   │   │   └── local_server.py
│   │   ├── transports/
│   │   │   ├── base.py
│   │   │   ├── cli.py
│   │   │   ├── http_ws.py
│   │   │   └── connectors/
│   │   └── stores/
│   │       ├── jsonl_sessions.py
│   │       ├── file_memory.py
│   │       └── fs_vault.py
│   ├── extensions/
│   │   ├── skills.py
│   │   ├── plugins.py
│   │   └── discovery.py
│   ├── app/
│   │   ├── bootstrap.py          # composition root
│   │   ├── lifecycle.py          # startup/shutdown, MCP ownership
│   │   └── scheduler.py
│   ├── cli/
│   │   └── entry.py
│   ├── skills/                   # built-in skills (markdown + yaml)
│   └── templates/                # prompt templates
└── tests/
    ├── unit/
    ├── integration/
    └── e2e/
```

Client assets (workbench) build to a bundled static directory owned by the local installation
and served by the HTTP/WS transport; they are never fetched or replaced by a remote host.

## 16. Module Specifications

Format: **Responsibility / Input / Output / State / Depends on / Forbidden.**

### 16.1 `domain`

- **Responsibility:** Define pure value types and typed errors for messages, turns, sessions,
  tool calls/results, and memory records.
- **Input:** None (constructed by callers).
- **Output:** Immutable/normalized data objects.
- **State:** None.
- **Depends on:** standard library only.
- **Forbidden:** I/O, config, any `newbot` module, third-party SDK imports, `Any`-typed fields.

### 16.2 `ports`

- **Responsibility:** Declare the interfaces the core needs (provider, tools, sessions, memory,
  transports, events, scheduler, versioning).
- **Input:** Calls from `core`/`app`.
- **Output:** Interface definitions only.
- **State:** None.
- **Depends on:** `domain`.
- **Forbidden:** Concrete implementations, I/O, reference to any adapter.

### 16.3 `policy`

- **Responsibility:** Decide safety: path containment, outbound URL legality, shell sandbox
  wrapping, transport access, and redaction.
- **Input:** Explicit values (raw path, workspace root, capability flags, URL, command, peer
  metadata) plus injected policy settings.
- **Output:** Decisions (`allowed`/`denied`/`resolved path`/`wrapped command`) or typed denial
  errors.
- **State:** Immutable policy settings injected at construction; no global mutable state.
- **Depends on:** `domain`, standard library.
- **Forbidden:** `core`, `adapters`, transports/providers, config globals read at call time.

### 16.4 `core/hub`

- **Responsibility:** Move envelopes between transports and the turn engine; fan out typed
  agent events to local subscribers and routed outbound delivery.
- **Input:** `InboundEnvelope` (from transports), `AgentEvent` (from turn/reasoning).
- **Output:** `OutboundEnvelope` (to transports), events (to subscribers).
- **State:** Subscriber registry, delivery queues. No conversation state.
- **Depends on:** `domain`, `ports`.
- **Forbidden:** Transport-specific wire formats, persistence, tool execution, provider calls.

### 16.5 `core/turn` (TurnEngine)

- **Responsibility:** Own the channel-facing turn: resolve session key + workspace scope,
  enqueue per session, assemble context, drive the reasoning loop, persist, publish reply.
- **Input:** `InboundEnvelope`, resolved `AgentDefinition`, ports.
- **Output:** `OutboundEnvelope`, session records, agent events.
- **State:** In-flight turn map (session → active turn + queue), cancellation tokens.
- **Depends on:** `domain`, `ports`, `policy`, `core.*`.
- **Forbidden:** Provider/transport/store concrete classes, wire formats, direct network I/O.

### 16.6 `core/reasoning` (ReasoningLoop)

- **Responsibility:** The model-facing loop: call the provider, stream deltas/reasoning, execute
  tool calls through the registry, feed results back, stop on final answer or budget.
- **Input:** Assembled context, `ToolRegistryPort`, `ProviderPort`, budget, cancellation.
- **Output:** Final message, tool-call transcript, streamed events.
- **State:** Iteration/character budget for the active turn only.
- **Depends on:** `domain`, `ports`, `core.budget`, `core.events`.
- **Forbidden:** Session persistence, transport details, workspace/policy decisions (delegated
  to tools + guards), delegation lifecycle.

### 16.7 `core/context` (ContextAssembler)

- **Responsibility:** Build the ordered, bounded model request from policy prompt, persona,
  project instructions, memory summary, and recent messages.
- **Input:** Session messages, memory summary, agent/project config, channel metadata.
- **Output:** Provider-ready message list + system prompt.
- **State:** None (pure assembly).
- **Depends on:** `domain`, `ports` (memory/session reads).
- **Forbidden:** Provider calls, tool execution, writing state.

### 16.8 `core/delegation` (SubagentManager)

- **Responsibility:** Create child sessions, run/cancel/message them, deliver results to origin,
  and mark interrupted children on restart.
- **Input:** Delegation request (task, context handle), control commands (status/instruct/wait/
  cancel).
- **Output:** Child turn events, delivered results/history.
- **State:** Child-task registry (parent ↔ children, status, partial results).
- **Depends on:** `domain`, `ports`, `core.turn` (as a service, not a subclass).
- **Forbidden:** Owning the parent's context, appearing as separate sessions in search,
  resuming interrupted tasks automatically.

### 16.9 `session`

- **Responsibility:** Persist and load session records; own compaction/checkpoints and session
  lifecycle (delete/fork semantics for subagents).
- **Input:** Records to append, session keys, compaction triggers.
- **Output:** Ordered message lists, checkpoint summaries, stored records.
- **State:** Session index; per-session file handles/locks.
- **Depends on:** `domain`, `ports` (store), `session.compaction`.
- **Forbidden:** Model/prompt logic, tool execution, transport formats, memory curation.

### 16.10 `memory`

- **Responsibility:** Own the journal, identity/durable files layout, consolidation of
  compacted turns, scheduled curation, and durable-file sanitization.
- **Input:** Compacted summaries, journal entries, durable file contents.
- **Output:** Journal appends, curated durable file edits, version records.
- **State:** Cursors, journal file, durable files.
- **Depends on:** `domain`, `ports` (store/versioning), `policy.redaction`.
- **Forbidden:** Provider/tool logic, session-file ownership, deciding turns to run.

### 16.11 `tools`

- **Responsibility:** Tool contract + registry + built-in tools (filesystem, shell, web, MCP,
  schedule, delegation, self-inspection).
- **Input:** `ToolCall` + `ToolContext`.
- **Output:** Normalized `ToolResult`; events.
- **State:** Registry contents (defined at composition); MCP client handles owned by `app`.
- **Depends on:** `domain`, `ports`, `policy`.
- **Forbidden:** `core` internals, transport/provider classes, raw chains of control over the
  turn.

### 16.12 `config`

- **Responsibility:** Schema, layered loading, `${VAR}` resolution, path helpers.
- **Input:** Config file, environment, CLI overrides.
- **Output:** Immutable resolved settings + resolved paths; typed load errors.
- **State:** None after load (settings are immutable).
- **Depends on:** `domain` (and the schema library).
- **Forbidden:** `core`, `adapters`, `tools`; writing resolved secrets to disk.

### 16.13 `adapters/providers`

- **Responsibility:** Implement `ProviderPort` for concrete LLM backends.
- **Input:** Provider-ready request, streaming callbacks.
- **Output:** Streamed deltas/reasoning, tool calls, final message; normalized errors.
- **State:** Per-provider client/session handles, retry/rate state.
- **Depends on:** `domain`, `ports`, `config`.
- **Forbidden:** `core` internals, sessions/memory, transports, policy decisions.

### 16.14 `adapters/transports`

- **Responsibility:** Translate platform I/O to/from envelopes; enforce transport access
  control; own wire protocol and local client assets.
- **Input:** Platform events, `OutboundEnvelope`.
- **Output:** `InboundEnvelope`, platform sends, wire events.
- **State:** Connection/session maps, auth state, capability negotiation.
- **Depends on:** `domain`, `ports`, `policy.access`, `config`.
- **Forbidden:** Agent execution, tool calls, provider calls, stores, core internals; serving
  remote-supplied executable assets.

### 16.15 `adapters/stores`

- **Responsibility:** Concrete persistence: JSONL sessions, file memory/journal, FS-backed
  version vault.
- **Input:** Records/contents to persist; load requests.
- **Output:** Loaded normalized records/contents; atomic write results.
- **State:** File locks, open handles, cursors.
- **Depends on:** `domain`, `ports`.
- **Forbidden:** Turn logic, prompt assembly, policy decisions, transport formats.

### 16.16 `extensions`

- **Responsibility:** Discover/load skills and plugins; validate manifests; surface MCP server
  definitions.
- **Input:** Workspace/config extension locations, plugin manifests.
- **Output:** Loaded skills and activation records.
- **State:** Loaded-extension index.
- **Depends on:** `domain`, `ports`, `config`.
- **Forbidden:** Core internals, executing tools directly, provider/transport classes.

### 16.17 `app`

- **Responsibility:** Composition root: load config, construct adapters, wire the core, own
  MCP/lifecycle, run the scheduler and curator, expose health.
- **Input:** Config + CLI flags.
- **Output:** Running runtime; lifecycle events.
- **State:** Object graph; process lifecycle.
- **Depends on:** everything.
- **Forbidden:** `cli`; embedding business logic that belongs in the core or an adapter.

### 16.18 `cli`

- **Responsibility:** Parse arguments and dispatch to `app`.
- **Input:** argv.
- **Output:** Process exit code.
- **State:** None.
- **Depends on:** `app`, `config`.
- **Forbidden:** Core/adapters internals, business logic.

## 17. Open Questions

1. **RAG adapter.** Whether to add an embeddings-backed retrieval port, or keep memory purely
   file-curated. Deferred; memory remains the architectural center either way.
2. **Multi-agent topology.** Whether collaborative topologies beyond parent/child delegation are
   needed, or delegation is sufficient.
3. **Workbench transport protocol.** The exact capability-negotiation format for the HTTP/WS
   transport (see §3.5, R1–R2), to be fixed in an implementation-phase ADR.
4. **Sandbox backends per OS.** Which OS sandbox backends ship by default, given fail-closed
   behavior on Windows.
