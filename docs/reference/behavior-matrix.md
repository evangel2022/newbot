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
| CLI | `onboard`/`status`/`agent`/`gateway`/`webui`/`serve`/`channels`/`plugins`; `--config`,`--workspace`; JSON config; Ctrl+C 130 | `init`/`run -m`/bare interactive/`compact`/`curate`/`serve`/`status`/`memory *`; `--config`; TOML config; `serve` runs config-declared recurring turns (`schedule.turns`), serves a bundled local client at `GET /`, and queues local triggers with `trigger <id> [message]`; 2=usage/config, 1=runtime, 130=interrupt | B (naming/format) + C (gateway, webui, channels, plugins) |
| Agent Loop | bus → session key → context → provider → tools → reply saved + sent; subagents, skills | hub → TurnEngine (one turn/session; cross-session concurrency bounded by `agent.maxConcurrentTurns`) → ContextAssembler → ReasoningLoop(budget) → tools → record + emit; events streamed | Match (core) + B (in-process subagents) |
| LLM | many providers, `provider: auto`, presets, fallbacks, temperature/context window | OpenAI-compatible only, explicit `provider.name`, `maxTokens`, SSE streaming | B (single-provider scope) + C (presets, fallbacks, auto-routing) |
| Tool Calling | auto-discovery incl. plugins; files/shell/web/MCP/cron/image/subagents; `enabledTools` | fixed built-ins `read_file`,`write_file`,`edit_file`,`apply_patch`,`list_dir`,`run_shell`,`web_fetch`,`web_search`, plus `cron`, configured stdio/HTTP MCP tools, a `skill` loader, a read-only `my` self-inspection, tools discovered from `newbot.tools` entry points, and a `delegate` subagent tool that can run, start, wait on, and cancel tasks; `[agent].tools` allowlist; normalized error results | Match (calling contract); C (image generation) |
| Session | key `channel:chat_id`; `unifiedSession`; JSONL outside workspace; `/new`,`/compact`; idle auto-compact; rate limit 6/min | key `transport:conversation`; JSONL under config dir; `historyLimit`; checkpoint compaction (explicit + size-triggered); one turn/session; scheduled turns record to their bound session; a Telegram chat is its own session (ADR-020) | B (trigger/keys) + C (unified, idle timer, rate limit) |
| Memory | `SOUL.md`/`USER.md`/`MEMORY.md`/`history.jsonl`; Dream; GitStore; `/dream*` | `persona.md`/`user.md`/`memory/knowledge.md`/`journal.jsonl`/`cursors.json`; cursor-based curation; vault versions; `memory *` | B (names/commands) + C (Dream guide file) |
| MCP | `tools.mcpServers` stdio/HTTP/SSE, OAuth, `enabledTools`, SSRF guard | stdio and HTTP servers via `[tools.mcp.servers]` or a plugin `mcp.json`, connected and discovered at startup (fail-fast), exposed as `mcp__<server>__<tool>` under `[agent].tools`; plugin stdio servers get contained `PLUGIN_ROOT`/`PLUGIN_DATA` and configured entries win collisions; HTTP requests are validated and pinned on every hop | B (single POST-only URL) + C (OAuth, SSE endpoint, per-server allowlist) |
| Configuration | `config.json`; camel+snake; `${VAR}` anywhere in a string; fail fast naming field+var | `config.toml`; camel alias + snake; unknown keys rejected; embedded `${VAR}` expansion (unset or malformed refs fail fast) | B (format/strictness) |
| Error Handling | layered diagnosis; config errors name the field; no tracebacks | `ConfigLoadError`→2, `NewbotError`→1, `KeyboardInterrupt`→130; turn failures become `TurnFailed`, never tracebacks; a failed outbound delivery is a terminal `TurnFailed`, not a retry (ADR-017) | Match |
| Security | `restrictToWorkspace` opt-in (default false); sandbox opt-in; SSRF + whitelist; pairing/allowFrom; localhost bind | workspace guard always-on with capability-specific roots; sandbox opt-in (fail-closed); SSRF + whitelist; token access (fail-closed); secret redaction; sessions outside workspace; a chat-id allowlist and a redacted channel token (ADR-020) | B (stricter defaults) + C (pairing, other chat channels) |

## Capability details

### 1. CLI

- **Contract.** Named subcommands with a version flag; `--config`/`--workspace` selectors on
  runtime commands; non-zero exit on usage/config errors; `Ctrl+C` yields 130.
- **Inputs.** argv; config path; message text.
- **Outputs.** stdout for replies/diagnostics; stderr for errors.
- **Exceptions.** None escape as tracebacks; argparse/usage and config errors are reported.
- **State.** `onboard`/`init` create config + workspace and never overwrite existing values.
- **newbot.** `--version`; `init` (create-only); `run -m`; bare = interactive; `compact`,
  `curate`, `serve`, `status`, `memory log|restore|revert-set`. `status` prints the resolved
  configuration without building a provider. `serve` runs each `[[schedule.turns]]`
  entry as a recurring turn in its bound `conversation`. Exit codes: 2 for usage/config, 1 for
  runtime errors, 130 for interrupt.
- **Evidence.** `tests/e2e/test_cli.py`, `tests/e2e/test_cli_smoke.py`,
  `tests/e2e/test_behavior_matrix.py::test_cli_*`,
  `tests/integration/test_serve.py::test_serve_runs_a_scheduled_turn_in_its_bound_conversation`,
  `tests/integration/test_triggers.py`,
  `tests/unit/app/test_status.py`.
- **Differences.** B: command names, TOML vs JSON, no Desktop picker, and scheduled turns and local triggers
  declared in config rather than created from a topic with a `cron` tool or `/trigger`
  (ADR-014, ADR-018). C: `gateway`, `webui`, `channels`, `plugins`, `onboard --wizard`.

### 2. Agent Loop

- **Contract.** One small loop: inbound message → session selection → context assembly →
  provider → tool calls fed back → reply persisted and delivered to the origin transport.
- **Inputs.** `InboundEnvelope(transport, conversation_id, text)`; provider stream events.
- **Outputs.** `OutboundEnvelope` to the origin transport; `TurnStarted`/`ResponseDelta`/
  `TurnCompleted`/`TurnFailed` events.
- **Exceptions.** Deliberate failures (`NewbotError`) are reported as `TurnFailed`, not raised
  through the transport.
- **State.** `(user, *produced)` messages appended to the session; one active turn per session;
  cross-session turns run concurrently unless `agent.maxConcurrentTurns` bounds them (ADR-015).
- **Evidence.** `tests/unit/core/test_turn.py`, `tests/unit/core/test_reasoning*.py`,
  `tests/e2e/test_cli.py::test_cli_runs_a_tool_end_to_end`,
  `tests/e2e/test_behavior_matrix.py::test_a_failed_turn_*`.
- **Differences.** A subagent runs as a child turn with isolated context through the
  `delegate` tool; it can run and wait, or run in the background and later be checked, waited
  on, or cancelled, with cancelling one child leaving siblings running (ADR-029, ADR-031,
  ADR-034), and a restart marks an unfinished task interrupted with its partial reply retained
  (ADR-033). C: Dream.

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
- **Evidence.** `tests/unit/tools/*`, `tests/unit/policy/test_workspace.py`, `tests/unit/extensions/test_discovery.py`,
  `tests/e2e/test_behavior_matrix.py::test_path_escape_*`.
- **Differences.** The agent can schedule, list, and remove session-bound jobs through the
  `cron` tool (ADR-021), call tools from configured stdio or HTTP MCP servers (ADR-022, ADR-024), and load
  workspace skills on demand through the `skill` tool (ADR-023), inspect its own configuration read-only through the
  `my` tool (ADR-025), load third-party tools from `newbot.tools` entry points (ADR-026), and
  delegate a self-contained task to a subagent (run, start, status, wait, cancel; ADR-029,
  ADR-031), and search the web through the built-in `web_search` tool (ADR-030). C: image
  generation; web search providers other than DuckDuckGo.

### 5. Session

- **Contract.** A session key derives from the transport plus conversation identity; history is
  append-only JSONL stored outside the agent workspace; compaction bounds the model context while
  keeping saved chat history; sessions persist across restarts.
- **Inputs.** `SessionKey`; recorded `Message`s.
- **Outputs.** Replay-safe `Message` tuple (summary + recent, no orphaned tool results).
- **Exceptions.** Store failures → `SessionError`.
- **State.** Append records; checkpoint record marks the context boundary.
- **Evidence.** `tests/unit/session/*`, `tests/integration/test_jsonl_sessions.py`,
  `tests/integration/test_serve.py::test_serve_runs_a_scheduled_turn_in_its_bound_conversation`,
  `tests/e2e/test_behavior_matrix.py::test_sessions_are_isolated_per_transport`,
  `::test_session_files_live_outside_the_workspace`.
- **Findings.** **A1** (fixed; see below). B: compaction triggers on size, not idle time; session keys
  are per transport; scheduled turns are config-declared and bound to a host conversation
  (ADR-014); local triggers are delivered at-least-once into their bound conversation with
  per-delivery deduplication and terminal failed marking (ADR-018); a config-declared heartbeat
  records its `HEARTBEAT.md` runs in its own conversation and never delivers a reply (ADR-019); a
  Telegram chat maps to its own session key `transport=telegram` (ADR-020). C: `unifiedSession`,
  idle auto-compact, `maxSessionMessagesPerMinute`, `/new`/`/stop` (newbot uses `/exit`).

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
- **newbot.** stdio and HTTP servers are configured under
  `[tools.mcp.servers.<name>]` or a plugin's `mcp.json`, started at composition (fail-fast),
  and exposed as `mcp__<server>__<tool>` filtered by `[agent].tools`; plugin stdio servers
  receive contained `PLUGIN_ROOT`/`PLUGIN_DATA`; HTTP endpoints are validated and pinned
  through the network guard before each request.
- **Inputs.** Per-server config (`command`/`args`/`env` or `url`); JSON-RPC `tools/list`
  and `tools/call`.
- **Outputs.** Namespaced `mcp__<server>__<tool>` specs and normalized text results.
- **Exceptions.** A server that cannot connect, rejects a request, or answers with an
  invalid payload becomes a typed `McpError`; a blocked HTTP target becomes
  `NetworkAccessDenied`; either fails startup.
- **State.** One live client per server; the transport is chosen by config; HTTP session
  ids are held per client and each server's `env` values (including plugin-bundled ones)
  are redacted.
- **Evidence.** `tests/integration/test_mcp.py`, `tests/unit/tools/test_mcp_tool.py`,
  `tests/unit/tools/test_mcp_http.py`,
  `tests/e2e/test_cli_smoke.py::test_cli_calls_a_tool_on_a_configured_mcp_server`,
  `tests/e2e/test_cli_smoke.py::test_cli_calls_a_tool_on_a_plugin_bundled_mcp_server`.
- **Differences.** **B** (see B4 and B6) plus **C**: OAuth, a separate SSE endpoint,
  server-initiated sampling/roots, and a per-server tool allowlist.

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
- **Findings.** **A2** (fixed; see below). B: TOML vs JSON, and strict rejection of unknown keys
  (`extra="forbid"`) where nanobot tolerates extra fields; nanobot's env
  `NANOBOT_MAX_CONCURRENT_REQUESTS` becomes the TOML field `agent.maxConcurrentTurns` (ADR-015).

### 9. Error Handling

- **Contract.** Failures are reported at the layer that owns them, without tracebacks; config
  problems are located; long-running processes read config at startup.
- **Inputs.** argv, config, provider responses, tool failures.
- **Outputs.** Human-readable `error:` lines; distinct exit codes.
- **Exceptions.** Mapped to exit codes: config/usage → 2, runtime → 1, interrupt → 130.
- **State.** A failed turn leaves the session replayable; a reply persisted before a delivery
  failure stays recorded, and every started turn ends in one terminal event.
- **Evidence.** `tests/e2e/test_cli.py`, `tests/integration/test_runtime.py`,
  `tests/e2e/test_behavior_matrix.py::test_a_failed_turn_is_reported_*`,
  `tests/unit/core/test_turn.py::test_delivery_failure_is_marked_failed_without_retry`.
- **Differences.** None material. A deliberate outbound-delivery failure is a terminal
  `TurnFailed` with no retry; the persisted reply stays in the session (ADR-017).

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
  `tests/e2e/test_behavior_matrix.py::test_path_escape_denial_is_a_bounded_tool_result`,
  `tests/integration/test_workbench.py::test_workbench_*ticket*`,
  `tests/integration/test_workbench.py::test_workbench_serves_no_asset_outside_its_bundle`.
- **Differences.** B: newbot's workspace guard is always on (nanobot defaults
  `restrictToWorkspace` to false) and its shell timeout default is 30s vs 60s. C: pairing and
  per-channel `allowFrom` beyond Telegram. B: the Telegram channel ignores chats outside
  `channels.telegram.allowedChatIds` when the list is set, and its bot token is redacted from logs,
  tool output, and the journal (ADR-020). B: browser WebSocket upgrades
  authenticate with a short-lived, single-use ticket carried as a subprotocol, never a token in
  the URL (nanobot documents a URL token; ADR-013). B: the workbench serves only its bundled
  local client, confined to the asset root and never a remote-supplied asset (ADR-016).

## Findings and resolution

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
  (regression test; unit coverage in `tests/unit/session/test_compaction.py`).
- **Suggested direction.** Keep pre-checkpoint records on disk (a checkpoint marks the context
  boundary; it need not delete records), or move them to an archive the session commands can
  read. `history()` already selects the summary + suffix, so retention does not change replay.
- **Resolution (fixed).** Compaction now keeps every saved `MessageRecord` and inserts the
  `CheckpointRecord` at the new replay boundary instead of dropping summarized records; `history()`
  already replays the summary plus the suffix, so replay is unchanged.

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
  (regression test; unit coverage in `tests/unit/config/test_loader.py`).
- **Suggested direction.** Expand embedded references (replace each match), and fail fast if a
  `${...}` substring remains unresolved so a typo cannot pass silently.
- **Resolution (fixed).** Every `${VAR}` reference embedded in a string is expanded; an unset
  variable or a malformed reference (`${}`, `${1BAD}`) raises `ConfigLoadError` at the owning field.

### B1 -- Heartbeat notifications are silent by construction

- **Contract.** nanobot `configuration.md#gateway-heartbeat` and `automations.md#heartbeat`: a
  protected heartbeat job reads `<workspace>/HEARTBEAT.md`, executes the tasks under
  `## Active Tasks`, and sends only useful or actionable results to the most recently active chat
  target. The notification gate is an LLM evaluator that fails closed to silence.
- **Observed.** When `heartbeat.enabled = true`, newbot's `serve` runs the file's active tasks in a
  dedicated conversation, records the turn, and never delivers a reply (`InboundEnvelope.reply =
  false`). The job is opt-in, and the target is a fixed config conversation, not the most recently
  active chat.
- **Classification.** **B -- intentional design difference.** newbot has no notification-gate tool
  and no channel-activity tracking, so v1 fails closed to silence, which keeps the "usually quiet"
  contract without an evaluator.
- **Evidence.** `tests/unit/app/test_heartbeat.py`,
  `tests/integration/test_serve.py::test_serve_runs_heartbeat_tasks_in_its_conversation`,
  `::test_serve_heartbeat_stays_quiet_without_active_tasks`, `::test_serve_heartbeat_is_opt_in`,
  `tests/unit/core/test_turn.py::test_turn_without_reply_records_history_but_delivers_nothing`.
- **Deferred (C).** nanobot's LLM notification gate, `keepRecentMessages`, a custom evaluator prompt,
  and `cron(action="list")` visibility (ADR-019).

### B2 -- Telegram channel: polling, allowlist, and text-only

- **Contract.** nanobot `chat-apps.md` and `configuration.md`: `channels.<channel>.enabled` plus
  credentials; a channel message maps to a session and the reply returns to that chat; Telegram,
  Discord, and Slack ship in-box, with pairing and `channels.*.allowFrom` for access control.
- **Observed.** newbot ships one channel, `channels.telegram`: it long-polls `getUpdates`, confirms
  the startup backlog without replaying it, maps each chat to its own session, and replies with
  `sendMessage`. `allowedChatIds` (empty means any chat) filters inbound chats, and the bot token is
  redacted from warnings, tool output, and the journal. Text messages only; no chat commands; a reply
  longer than Telegram's limit fails the delivery rather than being split.
- **Classification.** **B -- intentional design difference.** Polling suits a loopback-first host with
  no public ingress; an allowlist replaces pairing, which is deferred.
- **Evidence.** `tests/integration/test_telegram.py`,
  `tests/e2e/test_cli_smoke.py::test_serve_answers_a_telegram_message`,
  `tests/unit/config/test_loader.py::test_enabled_telegram_channel_requires_a_token`.
- **Deferred (C).** Discord/Slack, pairing and `allowFrom`, chat commands (`/new`, `/compact`),
  voice/image messages, chunked replies, and a persisted update cursor.

### B3 -- Scheduled jobs are session-bound, host-run, and interval-only

- **Contract.** nanobot `automations.md`: the `cron` tool creates, lists, and removes
  scheduled work; a protected heartbeat job appears in `cron(action="list")` and cannot be
  removed; jobs are persisted under the workspace so they survive a restart.
- **Observed.** newbot's `cron` tool (`add`/`list`/`remove`) binds each job to the calling
  session and stores it in `<workspace>/cron/jobs.json`; a `serve` poller dispatches due
  jobs into that session's conversation. `add` takes either `every_seconds` (recurring) or
  `delay_seconds` (one-shot). Recurring jobs schedule their next run from the dispatch
  time, so runs missed while the host was down are skipped; an overdue one-shot job runs
  once and is dropped. The registry is advanced before the turn runs, so a crash or a
  failed turn never replays a run. `list` shows only agent-created jobs -- the heartbeat is
  not included, and there is no pause, resume, or run-now.
- **Classification.** **B -- intentional design difference.** newbot has no cross-process
  scheduler daemon: jobs run only while `newbot serve` runs. Interval and delay scheduling
  cover the requested cases; cron expressions and timezones are deferred.
- **Evidence.** `tests/unit/tools/test_cron_tool.py`, `tests/integration/test_cron.py`,
  `tests/e2e/test_cli_smoke.py::test_serve_runs_an_agent_created_job_from_its_registry`,
  `tests/unit/core/test_turn.py::test_a_reply_to_an_unregistered_transport_fails_the_turn`.
- **Deferred (C).** cron expressions, timezones, absolute scheduling, pause/resume/run-now,
  and a heartbeat entry in `cron(action="list")`.

### B4 -- MCP startup is fail-fast and stdio-first

- **Contract.** nanobot `guides/configure-mcp-tools.md` and `configuration.md`:
  `tools.mcpServers` ships stdio (`command`/`args`/`env`) and HTTP/SSE (`url`) servers,
  exposes their tools under `enabledTools`, guards HTTP endpoints with SSRF checks, and
  leaves stdio servers outside the HTTP guard.
- **Observed.** newbot configures stdio servers under `[tools.mcp.servers.<name>]`,
  starts them at composition, and exposes each advertised tool as
  `mcp__<server>__<tool>` filtered by the global `[agent].tools` allowlist. Replies are
  parsed at the boundary, server stderr never enters context, and the server's `env`
  values are redacted. A server that cannot start, or that fails the handshake, fails
  the whole startup with a located error.
- **Classification.** **B -- intentional design difference.** stdio covers local tool
  servers, and fail-fast keeps a configured capability from silently disappearing.
  HTTP/SSE adds an SSRF-checked network boundary and landed in ADR-024 (B6).
- **Evidence.** `tests/integration/test_mcp.py`, `tests/unit/tools/test_mcp_tool.py`,
  `tests/e2e/test_cli_smoke.py::test_cli_calls_a_tool_on_a_configured_mcp_server`.
- **Deferred (C).** OAuth, server-initiated sampling/roots, a
  per-server tool allowlist, and plugin-bundled MCP servers.

### B5 -- Skills are workspace-only and load through a tool

- **Contract.** nanobot `concepts.md` and `configuration.md`: skills are markdown with
  YAML frontmatter under `<workspace>/skills/<name>/SKILL.md` (plus built-ins and
  plugin-bundled skills), loaded progressively or invoked with `$skill-name`, hidden with
  `agents.defaults.disabledSkills`, and resolved with workspace > plugin > built-in
  precedence.
- **Observed.** newbot discovers `<workspace>/skills/<name>/SKILL.md`, injects a catalog
  of names and descriptions into the system prompt, and returns one skill's body when the
  model calls the `skill` tool; the directory name is the skill name. A malformed skill is
  a located `SkillError` that fails startup, and an `[agent].tools` allowlist that omits
  `skill` hides the catalog too. Agent Plugins under `<workspace>/plugins/<name>/`
  contribute the skills they bundle through the same catalog, activated by
  `[plugins].enabled`; a workspace skill of the same name wins (ADR-027).
- **Classification.** **B -- intentional design difference.** Progressive loading is
  preserved without a chat-command surface, and fail-fast keeps a typo from silently
  removing guidance.
- **Evidence.** `tests/unit/extensions/test_skill_loading.py`,
  `tests/unit/tools/test_skill_tool.py`, `tests/integration/test_skills.py`,
  `tests/e2e/test_cli_smoke.py::test_cli_offers_a_workspace_skill_to_the_model`,
  `tests/unit/extensions/test_plugins.py`,
  `tests/e2e/test_cli_smoke.py::test_cli_offers_a_plugin_skill_to_the_model`.
- **Deferred (C).** Built-in skills, eager `PLUGIN_DATA` directory creation, `disabledSkills`,
  and `$skill-name` in-chat invocation.

### B6 -- HTTP MCP endpoints are POST-only and guarded on every request

- **Contract.** nanobot `configuration.md` and `guides/configure-mcp-tools.md`: an MCP
  server can be a `url` (HTTP/SSE); HTTP endpoints pass the SSRF guard; `enabledTools`
  narrows the exposed tools.
- **Observed.** newbot configures an HTTP server with `url` under
  `[tools.mcp.servers.<name>]` (exactly one of `command` or `url`). `HttpMcpClient` POSTs
  JSON-RPC to a single URL, accepts a JSON object or an SSE stream as the reply, echoes a
  server-assigned `Mcp-Session-Id`, and resolves and pins the target through the network
  guard before each request. Loopback/private targets are rejected with
  `NetworkAccessDenied` unless `[tools].ssrfWhitelist` opens a hole, and a non-2xx POST is
  a typed `McpError`.
- **Classification.** **B -- intentional design difference.** The streamable-HTTP
  transport is POST-only with a single URL, and startup fails fast like the stdio
  contract (B4).
- **Evidence.** `tests/unit/tools/test_mcp_http.py`, `tests/integration/test_mcp.py`.
- **Deferred (C).** OAuth, a separate SSE endpoint or chunked incremental streaming,
  server-initiated sampling/roots, and a per-server tool allowlist.

### B7 -- Self-inspection is read-only

- **Contract.** nanobot `docs/my-tool.md`: `my(action="check")` reads runtime state
  (model, workspace, limits, token usage, subagents) and `my(action="set", ...)` tunes
  mutable parameters (`max_iterations`, `model_preset`, scratchpad keys) with protected and
  blocked keys.
- **Observed.** newbot's `my` supports `action="check"` only. It reports a non-secret
  snapshot assembled by the composition root (`model`, `provider`, `max_iterations`,
  `sandbox`, `shell_timeout_seconds`, `allowed_tools`, `mcp_servers`) plus the per-turn
  `workspace` and `session`; an optional `key` drills into one top-level field. `set` is
  rejected, and the snapshot never contains provider keys, channel tokens, or MCP `env`
  secrets.
- **Classification.** **B -- intentional design difference.** Runtime tuning would let a turn
  mutate the shared instance resolved once at startup, and the subagent view has nothing to
  report until delegation exists.
- **Evidence.** `tests/unit/tools/test_my_tool.py`, `tests/unit/app/test_self_state.py`,
  `tests/e2e/test_cli_smoke.py::test_cli_reports_its_own_runtime_state`.
- **Deferred (C).** `set`/runtime tuning, a session scratchpad, token-usage reporting, and
  subagent monitoring.

### B8 -- Subagents run in-process across restarts

- **Contract.** nanobot `concepts.md`: a subagent is a child session with isolated context that
  reports progress/results to its origin conversation; background tasks deliver results when
  ready; a task can be checked, instructed, waited on, or cancelled; cancelling one leaves
  siblings running; unfinished tasks survive restart marked interrupted with partial results;
  `/stop` stops the session and its subagents.
- **Observed.** newbot's `delegate` tool runs a child turn with a derived session
  (`<conversation>:sub:<n>`), an isolated context containing only the task, and the shared tool
  registry; its history is recorded under the child session. `action="run"` waits for the reply;
  `action="start"` returns a task id and runs in the background; `status`, `wait`, and `cancel`
  address a task by id and are scoped to its origin conversation; cancelling one leaves siblings
  running. A finished background task publishes its reply to the origin conversation (ADR-032),
  and a one-shot or interactive exit waits for outstanding children. A child that calls
  `delegate` is refused, so delegation cannot recurse. Running tasks are persisted under
  `<workspace>/subagents/tasks.json`, and a restart marks a task left running as interrupted,
  keeping any partial reply (ADR-033). `/stop` cancels the current session's running child
  tasks and leaves other sessions untouched, and `agent.maxConcurrentTurns` bounds concurrently
  running children (ADR-034). The runtime's inbound handler also routes `/new`, `/stop`, and
  `/help` for every transport, with one shared resolver (ADR-035, ADR-036).
- **Classification.** **B -- intentional scope.** Background control, delivery, and a
  persistent registry exist; `/stop`, follow-up instructions, and a background concurrency bound
  are deferred.
- **Evidence.** `tests/unit/core/test_subagents.py`, `tests/unit/tools/test_delegate_tool.py`,
  `tests/unit/adapters/test_subagent_task_store.py`, `tests/integration/test_delegation_cli.py`.
- **Deferred (C).** Follow-up instructions to a running child, a dedicated out-of-turn
  delivery event, and the remaining chat commands (`/compact`, `/curate`, `/status`, `/model`).

### B9 -- Web search ships one HTML backend

- **Contract.** nanobot `configuration.md` and `guides/configure-web-search.md`:
  `web_search` and `web_fetch` are enabled by default and can be disabled with
  `tools.web.enable: false`; search selects one of many providers (DuckDuckGo default, plus
  API-backed and self-hosted options), with `maxResults`, proxy, and user-agent settings; the
  shared SSRF guard blocks private targets.
- **Observed.** newbot enables `web_search` and `web_fetch` by default and removes both when
  `[tools.web].enable` is false. `web_search` queries DuckDuckGo's HTML endpoint through the
  shared SSRF guard (pinned per request, redirects followed against the original host) and
  returns ranked title/URL/snippet results, capped by `[tools.web.search].maxResults` or the
  tool call's `max_results`. The backend sits behind a `SearchPort`, but only `duckduckgo` is
  implemented; any other provider is rejected at config load.
- **Classification.** **B -- intentional scope.** The provider seam is the documented
  extension point; the HTML backend is keyless and matches the documented default, but it is
  best-effort against a page whose markup can change.
- **Evidence.** `tests/unit/tools/test_web_search.py`,
  `tests/unit/tools/test_duckduckgo_search.py`.
- **Deferred (C).** API-backed providers (Brave/Tavily/Jina/Kagi/…), self-hosted SearXNG,
  proxy and user-agent settings, and result caching.

## Out of scope for this pass

nanobot behaviors with no newbot surface to compare yet (all **C**): Desktop/TUI integration,
chat channels other than Telegram (Discord/Slack/…), pairing, gateway lifecycle (`--background`,
service install),
OpenAI-compatible `serve` API, `/trigger` runtime creation,
the heartbeat notification gate (ADR-019), image
generation, transcription, Langfuse observability, project-workspace selection.
