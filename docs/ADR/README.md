# Architecture Decision Records

Each ADR records one significant decision for newbot: the context, the decision, its
consequences, and the alternatives rejected. ADRs are immutable once accepted; a reversal is a
new ADR that supersedes the old one.

| ADR | Title | Status |
| --- | --- | --- |
| [ADR-001](ADR-001-architecture.md) | Hexagonal architecture with a small core | Accepted |
| [ADR-002](ADR-002-agent-runtime.md) | Turn engine and reasoning loop split | Accepted |
| [ADR-003](ADR-003-tool-system.md) | Tool contract, registry, and policy injection | Accepted |
| [ADR-004](ADR-004-memory.md) | Two-tier memory with consolidation and curation | Accepted |
| [ADR-005](ADR-005-session.md) | Session identity, JSONL storage, and compaction | Accepted |
| [ADR-006](ADR-006-configuration.md) | Typed, layered, fail-fast configuration | Accepted |
| [ADR-007](ADR-007-security.md) | Boundary guards: workspace, network, sandbox, access | Accepted |
| [ADR-008](ADR-008-extension.md) | Extension points at the edges | Accepted |
| [ADR-009](ADR-009-testing.md) | Test by surface, protect real contracts | Accepted |
| [ADR-010](ADR-010-workbench-transport.md) | Workbench transport protocol | Accepted |
| [ADR-011](ADR-011-workbench-streaming.md) | Workbench streaming capability | Accepted |
| [ADR-012](ADR-012-bounded-workbench-request-bodies.md) | Bounded workbench request bodies | Accepted |
| [ADR-013](ADR-013-workbench-browser-auth.md) | Workbench browser authentication | Accepted |
| [ADR-014](ADR-014-config-declared-scheduled-turns.md) | Config-declared scheduled turns | Accepted |
| [ADR-015](ADR-015-bounded-turn-concurrency.md) | Bounded cross-session turn concurrency | Accepted |
| [ADR-016](ADR-016-locally-served-workbench-assets.md) | Locally served workbench assets | Accepted |
| [ADR-017](ADR-017-failed-delivery-is-terminal.md) | Failed outbound delivery is terminal | Accepted |
| [ADR-018](ADR-018-local-trigger-queue.md) | Local trigger delivery queue | Accepted |
| [ADR-019](ADR-019-heartbeat.md) | Workspace heartbeat | Accepted |
| [ADR-020](ADR-020-telegram-channel.md) | Telegram chat channel | Accepted |
| [ADR-021](ADR-021-cron-tool.md) | Agent-created scheduled jobs | Accepted |
| [ADR-022](ADR-022-mcp-tools.md) | Model Context Protocol tools (stdio) | Accepted |
| [ADR-023](ADR-023-workspace-skills.md) | Workspace skills | Accepted |
| [ADR-024](ADR-024-mcp-http-transport.md) | HTTP MCP transport | Accepted |
| [ADR-025](ADR-025-self-inspection-tool.md) | Read-only self-inspection tool | Accepted |
| [ADR-026](ADR-026-entry-point-tool-discovery.md) | Entry-point tool discovery | Accepted |
| [ADR-027](ADR-027-agent-plugin-packages.md) | Agent Plugin packages (skills) | Accepted |
| [ADR-028](ADR-028-plugin-bundled-mcp-servers.md) | Plugin-bundled MCP servers | Accepted |
| [ADR-029](ADR-029-in-process-delegation.md) | In-process delegation | Accepted |
| [ADR-030](ADR-030-web-search.md) | Web search tool and provider seam | Accepted |
| [ADR-031](ADR-031-background-subagent-tasks.md) | Background subagent tasks | Accepted |
| [ADR-032](ADR-032-background-result-delivery.md) | Background result delivery | Accepted |
| [ADR-033](ADR-033-persistent-subagent-tasks.md) | Persistent subagent task registry | Accepted |
| [ADR-034](ADR-034-subagent-stop-and-concurrency.md) | Subagent stop command and concurrency bound | Accepted |
| [ADR-035](ADR-035-runtime-command-routing.md) | Runtime command routing | Accepted |
| [ADR-036](ADR-036-runtime-new-command.md) | `/new` and unified command replies | Accepted |

Normative source: [../ARCHITECTURE.md](../ARCHITECTURE.md).
