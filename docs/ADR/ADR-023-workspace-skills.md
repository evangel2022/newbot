# ADR-023: Workspace Skills

- Status: Accepted
- Date: 2026-10-05
- Supersedes: none

## Context

The architecture's extension model lists skills as "markdown + YAML frontmatter under workspace
`skills/` or built-ins" in `extensions/skills`, and its first principle is that know-how belongs in
a skill rather than in the agent loop. nanobot (`concepts.md`, `configuration.md`) discovers skills
under `<workspace>/skills/<name>/SKILL.md`, loads their guidance progressively, invokes them with
`$skill-name`, and can hide them with `agents.defaults.disabledSkills`. newbot had no skills
surface, so the behavior matrix records skills as **C -- not implemented**.

## Decision

Discover workspace skills, advertise a catalog, and load one body on demand.

- `domain/skill.py` adds `Skill` (name, description, body). `extensions/skills.py` owns discovery:
  every `<workspace>/skills/<name>/SKILL.md` becomes a skill, ordered by directory name. The
  directory name is the skill name and must match `[A-Za-z0-9._-]{1,64}`; a directory without
  `SKILL.md` is not a skill and is ignored.
- The file is markdown with YAML frontmatter. The frontmatter is dynamic input, so it is parsed at
  the boundary with `yaml.safe_load` and validated with a pydantic model that requires a non-empty
  `description` and ignores unknown keys (a skill may carry `license`, `allowed-tools`, and so on).
  A missing frontmatter block, invalid YAML, or a missing description is a located `SkillError`.
- `tools/skills.py` adds the `skill` tool: `action: "list"` returns the catalog, `read` returns one
  body by name, and an unknown name is an error result. The tool holds the loaded catalog, so it
  never touches the filesystem at call time.
- The composition root, not the core, surfaces the catalog. `build_runtime` loads the skills,
  appends `render_skill_summary(...)` -- names and descriptions only -- to the configured system
  prompt, and registers `SkillTool`. `ContextAssembler` and every `core/` file are unchanged.
- Skills are advertised only when the `skill` tool survives the `[agent].tools` allowlist; an
  allowlist that omits `skill` hides both the tool and the catalog, so the prompt never points at a
  tool the model cannot call.
- A malformed skill fails startup: the operator wrote the file deliberately, so a typo should be
  loud rather than silently absent from the catalog.

## Consequences

**Positive**

- Know-how is added at the edge: a new skill is a markdown file, and no core or tool code changes.
- Context stays small: the prompt carries only names and descriptions, and a body enters context
  only when the model asks for it.
- The frontmatter boundary is validated once, with a located error naming the file.

**Negative / accepted costs (deliberate differences, B)**

- **B -- the directory name is the skill name.** The frontmatter `name` is ignored; nanobot also
  keys `disabledSkills` and precedence by directory.
- **B -- no `$skill-name` chat command.** A skill is loaded through the `skill` tool, not a chat
  command, because newbot has no in-chat command surface yet.
- **B -- no built-ins, plugins, or precedence.** Only workspace skills exist; plugin- and
  built-in-bundled skills, `plugins/`, and `disabledSkills` are deferred until a skill ships in-box
  or a plugin can bundle one.
- **B -- fail-fast.** A malformed skill stops startup; nanobot can skip it.

## Alternatives considered

- **Injecting every skill body into the system prompt.** Rejected: it defeats progressive loading
  and inflates every request.
- **A `disabledSkills` config now.** Deferred (ADR-008): newbot ships no skills, so there is nothing
  to disable that deleting the file would not also fix; the knob returns with built-ins or plugins.
- **A hand-rolled YAML subset parser.** Rejected: the frontmatter is a real YAML boundary, and
  PyYAML is the reference behaviour; a subset parser would silently misread valid files.
- **Registering the `skill` tool even with no skills.** Rejected: a tool that can only report "no
  skills" is noise in every request.
