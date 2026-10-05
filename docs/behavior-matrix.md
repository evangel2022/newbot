# Behavior Matrix: nanobot vs newbot

Status: Phase 1 validation (2026-10-05)
Owners: `docs/behavior-matrix.md` (this file), tests in `tests/e2e/test_behavior_matrix.py`

## Purpose and method

This document compares **nanobot's documented public behavior** with **newbot's observed public
behavior**. It is a behavior comparison, not a code comparison: nanobot's source is not in this
repository, so the reference contract is its published documentation under `docs/` (CLI reference,
configuration, memory, providers, chat commands, troubleshooting, security, and MCP guides).
newbot's behavior is observed through its public boundaries (CLI, HTTP/WS transport, config loader)
and the existing test suite.

For each capability this document records the contract, inputs, outputs, exceptions, and state
changes, then classifies every difference as:

- **A — bug**: newbot contradicts the contract or its own ADRs.
- **B — intentional design difference**: newbot deliberately differs; the difference is recorded
  and accepted.
- **C — not implemented**: the capability or sub-capability does not exist yet in newbot.

Evidence column refers to the test that protects the contract. Where a contract is already
protected by an existing test, this phase **reuses that evidence** (ADR-009 T5) instead of adding
a duplicate; `tests/e2e/test_behavior_matrix.py` adds only the contracts that were not covered.

## Summary matrix

| Capability | nanobot (documented) | newbot (observed) | Status |
|---|---|---|---|
| CLI | `onboard`/`status`/`agent`/`gateway`/`webui`/`serve`/`channels`/`plugins`; `--config`,`--workspace`; JSON config; Ctrl+C 130 | `init`/`run -m`/bare interactive/`compact`/`curate`/`serve`/`memory *`; `--config`; TOML config; 2=usage/config, 1=runtime, 130=interrupt | B (naming/format) + C (status, gateway, webui, channels, plugins) |
| Agent Loop | bus → session key → context → provider → tools → reply saved + sent; subagents, skills | hub → TurnEngine (one turn/session) → ContextAssembler → ReasoningLoop(budget) → tools → record + emit; events streamed | Match (core); C (subagents, skills) |
| LLM | many providers, `provider: auto`, presets, fallbacks, temperature/context window | OpenAI-compatible only, explicit `provider.name`, `maxTokens`, SSE streaming | B (single-provider scope) + C (presets, fallbacks, auto-routing) |
| Tool Calling | auto-discovery incl. plugins; files/shell/web/MCP/cron/image/subagents; `enabledTools` | fixed built-ins `read_file`,`write_file`,`list_dir`,`run_shell`,`web_fetch`; `[agent].tools` allowlist; normalized error results | Match (calling contract); C (MCP/cron/image/subagents, plugin discovery) |
| Session | key `channel:chat_id`; `unifiedSession`; JSONL outside workspace; `/new`,`/compact`; idle auto-compact; rate limit 6/min | key `transport:conversation`; JSONL under config dir; `historyLimit`; checkpoint compaction (explicit + size-triggered); one turn/session | B (trigger/keys) + **A1** + C (unified, idle timer, rate limit) |
| Memory | `SOUL.md`/`USER.md`/`MEMORY.md`/`history.jsonl`; Dream; GitStore; `/dream*` | `persona.md`/`user.md`/`memory/knowledge.md`/`journal.jsonl`/`cursors.json`; cursor-based curation; vault versions; `memory *` | B (names/commands) + C (Dream guide file) |
| MCP | `tools.mcpServers` stdio/HTTP/SSE, OAuth, `enabledTools`, SSRF guard | none | C |
| Configuration | `config.json`; camel+snake; `${VAR}` anywhere in a string; fail fast naming field+var | `config.toml`; camel alias + snake; unknown keys rejected; `${VAR}` only as a whole value | B (format/strictness) + **A2** |
| Error Handling | layered diagnosis; config errors name the field; no tracebacks | `ConfigLoadError`→2, `NewbotError`→1, `KeyboardInterrupt`→130; turn failures become `TurnFailed`, never tracebacks | Match |
| Security | `restrictToWorkspace` opt-in (default false); sandbox opt-in; SSRF + whitelist; pairing/allowFrom; localhost bind | workspace guard always-on with capability-specific roots; sandbox opt-in (fail-closed); SSRF + whitelist; token access (fail-closed); secret redaction; sessions outside workspace | B (stricter defaults) + C (pairing, chat channels) |

## Capability details

### 1. CLI

- **Contract.** Named subcommands with a version flag; `--config`/`--workspace` selectors on
  runtime commands; non-zero exit on usage/config errors; `Ctrl+C` yields 130.
- **Inputs.** argv; config path; message text.
- **Outputs.** stdout for replies/diagnostics; stderr for errors.
- **Exceptions.** None escape as tracebacks; argparse/usage and config errors are reported.
- **State.** `onboard`/`init` create config + workspace and never overwrite existing values.
- **newbot.** `--version`; `init` (create-only); `run -m`; bare = interactive; `compact`,
  `curate`, `serve`, `memory log|restore|revert-set`. Exit codes: 2 for usage/config, 1 for
  runtime errors, 130 for interrupt.
- **Evidence.** `tests/e2e/test_cli.py`, `tests/e2e/test_cli_smoke.py`,
  `tests/e2e/test_behavior_matrix.py::test_cli_*`.
- **Differences.** B: command names, TOML vs JSON, no Desktop picker. C: `status`, `gateway`,
  `webui`, `channels`, `plugins`, `trigger`, `onboard --wizard`.

### 2. Agent Loop

- **Contract.** One small loop: inbound message → session selection → context assembly →
  provider → tool calls fed back → reply persisted and delivered to the origin transport.
- **Inputs.** `InboundEnvelope(transport, conversation_id, text)`; provider stream events.
- **Outputs.** `OutboundEnvelope` to the origin transport; `TurnStarted`/`ResponseDelta`/
  `TurnCompleted`/`TurnFailed` events.
- **Exceptions.** Deliberate failures (`NewbotError`) are reported as `TurnFailed`, not raised
  through the transport.
- **State.** `(user, *produced)` messages appended to the session; one active turn per session.
- **Evidence.** `tests/unit/core/test_turn.py`, `tests/unit/core/test_reasoning*.py`,
  `tests/e2e/test_cli.py::test_cli_runs_a_tool_end_to_end`,
  `tests/e2e/test_behavior_matrix.py::test_a_failed_turn_*`.
- **Differences.** C: subagents, skills, Dream, heartbeat.

### 3. LLM

- **Contract.** Provider selection is explicit and traceable; the request carries model, system
  prompt, messages, tools, and optional max tokens; the response streams text and tool calls.
- **Inputs.** `ProviderSettings`; `ModelRequest`.
- **Outputs.** `StreamEvent` sequence ending in `Completed`.
- **Exceptions.** Non-2xx, transport failure, or malformed chunk → `ProviderError`.
- **State.** None (the client is closed on shutdown).
- **Evidence.** `tests/integration/test_openai_compatible.py`,
  `tests/e2e/test_behavior_matrix.py::test_unknown_provider_name_fails_fast`.
- **Differences.** B: only `openai_compatible`. C: `provider: auto`, prefix inference, model
  presets, fallback chains, OAuth providers, Bedrock.

### 4. Tool Calling

- **Contract.** Tools expose a spec; a call is validated at the boundary; a failed call becomes a
  bounded error result rather than an exception; results are normalized before entering context.
- **Inputs.** `ToolCall(id, name, arguments)`; `ToolContext`.
- **Outputs.** `ToolResult(call_id, content, is_error)`; enabled `ToolSpec` list.
- **Exceptions.** Unknown tool, invalid arguments, or guard denial → `is_error` result.
- **State.** Files/shell effects are confined by the guards; results are bounded and redacted.
- **Evidence.** `tests/unit/tools/*`, `tests/unit/policy/test_workspace.py`,
  `tests/e2e/test_behavior_matrix.py::test_path_escape_*`.
- **Differences.** C: MCP tools, cron, image generation, subagents, edit/patch tools, runtime
  discovery from entry points.

### 5. Session

- **Contract.** A session key derives from the transport plus conversation identity; history is
  append-only JSONL stored outside the agent workspace; compaction bounds the model context while
  keeping saved chat history; sessions persist across restarts.
- **Inputs.** `SessionKey`; recorded `Message`s.
- **Outputs.** Replay-safe `Message` tuple (summary + recent, no orphaned tool results).
- **Exceptions.** Store failures → `SessionError`.
- **State.** Append records; checkpoint record marks the context boundary.
- **Evidence.** `tests/unit/session/*`, `tests/integration/test_jsonl_sessions.py`,
  `tests/e2e/test_behavior_matrix.py::test_sessions_are_isolated_per_transport`,
  `::test_session_files_live_outside_the_workspace`.
- **Findings.** **A1** (see below). B: compaction triggers on size, not idle time; session keys
  are per transport. C: `unifiedSession`, idle auto-compact, `maxSessionMessagesPerMinute`,
  `/new`/`/stop` (newbot uses `/exit`).

### 6. Memory

- **Contract.** Durable, human-readable memory files plus an append-only history; curation
  consumes new history through a cursor; every change is versioned and restorable.
- **Inputs.** Journal entries; curation edits from the interpreter.
- **Outputs.** Updated durable files; a change-set id; version list.
- **Exceptions.** Curation failure → `CurationError`; unknown version/change-set → `NewbotError`.
- **State.** Journal is append-only; a cursor records what has been consumed; the vault records
  file versions; restore/revert rewrite durable files.
- **Evidence.** `tests/integration/test_curation.py`, `tests/integration/test_fs_vault.py`,
  `tests/unit/memory/test_journal.py`, `tests/e2e/test_behavior_matrix.py::test_memory_layout_*`.
- **Differences.** B: file/command names. C: Dream prompt guide (`prompts/dream.md`), GitStore.

### 7. MCP

- **Contract.** `tools.mcpServers` exposes stdio/HTTP/SSE servers as model tools with tool
  filtering (`enabledTools`), timeouts, and SSRF validation for HTTP endpoints.
- **newbot.** No MCP code path exists (`src/newbot` has no MCP module).
- **Differences.** **C — not implemented.** No test is added for an unimplemented capability
  (ADR-009: no tests for unsupported combinations).

### 8. Configuration

- **Contract.** Typed, layered config resolved once at startup; camelCase and snake_case both
  accepted; `${VAR}` references resolved from the environment without writing secrets back;
  unresolved references and invalid files fail fast with a located error.
- **Inputs.** Config file (TOML for newbot, JSON for nanobot); environment.
- **Outputs.** Immutable `Settings`.
- **Exceptions.** `ConfigLoadError` naming the field, with `error: ...` on stderr.
- **State.** None; secrets are never persisted.
- **Evidence.** `tests/unit/config/test_loader.py`, `tests/unit/config/test_init.py`,
  `tests/e2e/test_behavior_matrix.py::test_env_reference_*`.
- **Findings.** **A2** (see below). B: TOML vs JSON, and strict rejection of unknown keys
  (`extra="forbid"`) where nanobot tolerates extra fields.

### 9. Error Handling

- **Contract.** Failures are reported at the layer that owns them, without tracebacks; config
  problems are located; long-running processes read config at startup.
- **Inputs.** argv, config, provider responses, tool failures.
- **Outputs.** Human-readable `error:` lines; distinct exit codes.
- **Exceptions.** Mapped to exit codes: config/usage → 2, runtime → 1, interrupt → 130.
- **State.** A failed turn records nothing partial and leaves the session replayable.
- **Evidence.** `tests/e2e/test_cli.py`, `tests/integration/test_runtime.py`,
  `tests/e2e/test_behavior_matrix.py::test_a_failed_turn_is_reported_*`.
- **Differences.** None material.

### 10. Security

- **Contract.** Workspace confinement, SSRF protection, opt-in OS sandboxing with fail-closed
  behavior, transport access control, and secret redaction.
- **Inputs.** Paths, URLs, shell commands, transport headers, tool output.
- **Outputs.** Denials (`PathAccessDenied`, `NetworkAccessDenied`, `ToolError`) or permitted
  results with secrets redacted.
- **Exceptions.** Guard denials surface as typed errors or bounded error results.
- **State.** No state escapes the workspace; session files live outside it.
- **Evidence.** `tests/unit/policy/test_workspace.py`, `tests/unit/policy/test_network.py`,
  `tests/unit/policy/test_shell.py`, `tests/unit/policy/test_sandbox.py`,
  `tests/unit/policy/test_access.py`, `tests/unit/policy/test_redaction.py`,
  `tests/e2e/test_behavior_matrix.py::test_path_escape_denial_is_a_bounded_tool_result`.
- **Differences.** B: newbot's workspace guard is always on (nanobot defaults
  `restrictToWorkspace` to false) and its shell timeout default is 30s vs 60s. C: pairing and
  per-channel `allowFrom` (newbot has no chat channels yet).

## Findings requiring action

### A1 — Session compaction destroys saved history

- **Contract.** nanobot `chat-commands.md`: `/compact` summarizes context "while keeping saved
  chat history"; `memory.md`: "The complete session history remains stored for later inspection".
  newbot's own ADR-005 Consequences: "Checkpoints bound context size **without destroying saved
  history**" and "records before it are represented by a summary".
- **Observed.** `SessionManager.compact` calls `_rewrite_with_summary`, which writes
  `(CheckpointRecord, *tail[keep_recent:])` via `store.rewrite`, permanently dropping the
  summarized message records from the JSONL file. Probe: 6 records → `compact(keep_recent=2)` →
  3 records; `msg-0` is no longer present on disk.
- **Impact.** `/compact` and size-triggered auto-compaction are irreversible: users cannot
  inspect, audit, or restore the pre-compaction conversation, contradicting both the reference
  contract and newbot's ADR-005.
- **Classification.** **A — bug** (newbot violates its own ADR and the reference contract).
- **Test.** `tests/e2e/test_behavior_matrix.py::test_compaction_keeps_saved_history_on_disk`
  (`xfail` until fixed).
- **Suggested direction.** Keep pre-checkpoint records on disk (a checkpoint marks the context
  boundary; it need not delete records), or move them to an archive the session commands can
  read. `history()` already selects the summary + suffix, so retention does not change replay.

### A2 — `${VAR}` references are only expanded as a whole value

- **Contract.** nanobot `configuration.md`: "Any string value in `config.json` can use
  `${VAR_NAME}`", with the example `"Authorization": "Bearer ${REMOTE_MCP_TOKEN}"`.
- **Observed.** `config/loader.py` matches with `_ENV_REF.fullmatch`, so only a value that is
  exactly one reference is expanded; `"Bearer ${TOKEN}"` is left literal and is then sent/used
  verbatim, with no error. Probe: `apiKey = "Bearer ${TOKEN}"` → `'Bearer ${TOKEN}'`;
  `apiKey = "${TOKEN}"` → `'secret-value'`.
- **Impact.** A common pattern silently sends an unresolved placeholder instead of the secret,
  producing an authentication failure far from the cause (and a confusing on-wire value).
- **Classification.** **A — bug** (silent partial expansion).
- **Test.** `tests/e2e/test_behavior_matrix.py::test_env_reference_inside_a_larger_string_is_expanded`
  (`xfail` until fixed).
- **Suggested direction.** Expand embedded references (replace each match), and fail fast if a
  `${...}` substring remains unresolved so a typo cannot pass silently.

## Out of scope for this pass

nanobot behaviors with no newbot surface to compare yet (all **C**): Desktop/TUI integration,
chat channels (Telegram/Discord/Slack/…), gateway lifecycle (`--background`, service install),
OpenAI-compatible `serve` API, plugins/skills, cron/triggers/heartbeat, subagents, image
generation, transcription, Langfuse observability, project-workspace selection.
