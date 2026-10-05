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

Normative source: [../ARCHITECTURE.md](../ARCHITECTURE.md).