# ADR-026: Entry-Point Tool Discovery

- Status: Accepted
- Date: 2026-10-06
- Supersedes: none

## Context

ADR-008 names the tool extension points as "under `tools/` or an entry point", and Phase 5 lists
entry-point tool discovery as a deliverable. A third-party distribution must be able to add a
model-callable tool without editing the core, the registry, or the composition root. ADR-008 also
requires discovery to be deterministic, side-effect free, and traceable, and forbids hidden
capability: an operator must be able to trace an enabled tool to the distribution that provided
it.

The existing `Tool` contract lived in `tools/base.py`. The `extensions` layer may not import
`tools` (ADR-001/A2), so discovery could not name the contract it loads and returns.

## Decision

Move the `Tool` protocol and its `ToolOutput` value type into `ports/tools.py` (re-exported from
`tools/base.py`), and add `extensions/discovery.py`:

- `DISCOVERY_GROUP = "newbot.tools"` is the one entry-point group newbot reads.
- Each entry point resolves to a zero-argument factory returning a `Tool`.
- `discover_tools(group=DISCOVERY_GROUP, *, entry_points=None)` returns `DiscoveredTool(origin,
  tool)` records sorted by entry-point name. The `entry_points` argument is an injection seam for
  tests; the default reads `importlib.metadata`.
- The composition root (`app/bootstrap.py`) calls discovery once per runtime and passes the tools
  to `build_default_registry(discovered_tools=...)`, so they obey the `[agent].tools` allowlist
  and the registry's duplicate-name check exactly like built-ins.
- Discovery fails fast and is validated at the boundary: an entry point that cannot import, that
  does not resolve to a callable, that raises while building, that returns a non-`ToolSpec` spec,
  an empty name, or an object without `invoke()` raises a located `ExtensionError` and aborts
  startup. Two entry points offering the same tool name is likewise an error.

## Consequences

**Positive**

- A distribution can ship a tool by declaring one entry point; no core or registry change.
- Provenance is preserved in `DiscoveredTool.origin`, and the loaded set is name-sorted, so
  enablement is deterministic and inspectable.
- Validation happens where untrusted code enters, matching the "validate at boundaries" rule.

**Negative / accepted costs**

- A broken installed distribution now fails every startup rather than dropping its tool. This is
  deliberate: a configured capability that silently vanished would hide the misconfiguration.
- The `Tool`/`ToolOutput` move is a small refactor; implementations that import from
  `tools/base.py` keep working through the re-export.

## Alternatives considered

- **Import-time auto-discovery.** Rejected by ADR-008: hidden capability and unclear provenance.
- **Discovery inside `tools/registry.py`.** Rejected: the `tools` layer must not read entry-point
  metadata or own composition; the composition root owns what is enabled.
- **A plugin manifest file instead of entry points.** Deferred: entry points give free
  distribution provenance and need no manifest format; plugin packages that bundle skills and MCP
  servers remain a separate deliverable.
- **Keeping `Tool` in `tools/base.py`.** Rejected: `extensions` cannot import `tools`, so
  discovery would have to return an untyped value.
