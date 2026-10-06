# ADR-027: Agent Plugin Packages (Skills)

- Status: Accepted
- Date: 2026-10-06
- Supersedes: none

## Context

ADR-008 lists the plugin extension point as a "package bundling skills and/or MCP servers",
and Phase 5 lists `extensions/plugins.py`. The reference documents Agent Plugins v1: a package
under `<workspace>/plugins/` with a `plugin.json` manifest that may add `mcp.json`,
`skills/<name>/SKILL.md`, or both. Directory presence means installed; activation is explicit;
skills resolve with workspace > plugin > built-in precedence; invalid or escaping components are
ignored.

newbot already loads workspace skills (`extensions/skills.py`) and feeds them to the `skill`
tool. What was missing was the package and activation boundary that lets an operator install a
self-contained capability without editing the workspace's own `skills/`.

## Decision

Add Agent Plugin discovery for the skills a package bundles, and defer the MCP half.

- `domain/plugin.py` adds `Plugin(name, root, skills)`.
- `extensions/plugins.py` adds:
  - `discover_plugins(workspace_root, *, enabled)`: for each name in `enabled`, require
    `<workspace>/plugins/<name>/plugin.json`, validate it as a JSON object with a non-empty
    `name` that matches the directory, load bundled skills through the existing `load_skills`,
    and reject any component that resolves outside the plugin root.
  - `merge_skills(primary, plugins)`: merge plugin skills under the workspace's, which wins name
    collisions; a skill bundled by two plugins is an error; the result is name-sorted.
- Configuration gains `[plugins].enabled = [...]`, validated for name shape and duplicates.
- The composition root wires discovery and merging next to workspace skills; `my` and `status`
  report the enabled plugin names.

Activation is config-declared (`[plugins].enabled`), not a WebUI/Apps flow: an installed package
stays inert until the operator names it, so directory presence alone never grants capability.

Failure is loud. A plugin named in config but not installed, an unreadable or invalid manifest, a
manifest whose name disagrees with its directory, a bundled skill that fails to load, a
component that escapes the plugin root, or one skill bundled by two plugins aborts startup.

## Consequences

**Positive**

- A plugin is a self-contained, relocatable package; enabling it does not edit workspace files.
- Provenance is explicit: the enabled names come from config, and `status`/`my` report them.
- The skills path, the `skill` tool, the system-prompt catalog, and the allowlist are reused
  unchanged, so plugin skills behave exactly like workspace skills.

**Negative / accepted costs (deliberate differences, B)**

- **B -- config activation, not Apps.** The reference activates plugins through the WebUI/Apps
  surface. newbot has no Apps surface yet, so `[plugins].enabled` is the activation record.
- **B -- manifest is minimal.** Only `name` is read; unknown keys are ignored for forward
  compatibility. Immutability hashing, the optional logo, and permission descriptors are not
  implemented.
- **B -- escaping components are an error, not ignored.** An enabled package that points outside
  its root fails startup, matching newbot's fail-fast posture.

**Deferred (C)**

- Bundled `mcp.json` servers, `PLUGIN_ROOT`/`PLUGIN_DATA` containment, skill precedence across
  built-ins, `disabledSkills`, and `$skill-name` in-chat invocation.

## Alternatives considered

- **Entry-point plugins.** Rejected: ADR-008 scopes entry points to tools; the documented plugin
  boundary is a workspace package.
- **Enable any installed package by presence.** Rejected: hidden capability and unclear
  provenance (ADR-008).
- **Reuse the workspace `skills/` layout without a manifest.** Rejected: no place to name the
  package, record provenance, or reserve the future `mcp.json`.
- **Load bundled MCP servers now.** Deferred: it needs an `mcp.json` shape and
  `PLUGIN_ROOT`/`PLUGIN_DATA` semantics that this slice cannot validate against the reference.
