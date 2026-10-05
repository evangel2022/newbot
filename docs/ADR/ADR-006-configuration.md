# ADR-006: Typed, Layered, Fail-Fast Configuration

- Status: Accepted
- Date: 2026-10-05
- Supersedes: —

## Context

newbot has many knobs (providers, transports, tools, security, scheduling) and must stay
predictable across CLI, environment, and file inputs. Silent coercion or recovery from a broken
config is dangerous for a system with filesystem, shell, and network access. Secrets must never
be written back to disk. Config also determines which adapters are constructed, so resolution
must be traceable from setting to concrete class.

## Decision

- **Typed schema.** All configuration lives in Pydantic models in `config/schema.py`. Unknown
  keys are rejected or explicitly ignored — never silently coerced.
- **Layering.** Effective config resolves in order: built-in defaults → config file →
  `${VAR}` environment expansion → CLI flags. It resolves once at startup into an immutable
  settings object; runtime code receives the settings, not raw config.
- **Fail fast.** A missing referenced variable or an invalid file raises a typed load error with
  field locations. Defaults are created only when the file is absent; an invalid file is never
  "recovered" from.
- **Key style.** The schema accepts both `camelCase` and `snake_case` on read and writes
  `camelCase` on save, keeping on-disk config stable.
- **Paths.** Two roots are distinguished: the **config dir** (config, sessions, logs, media,
  runtime data) and the **agent workspace** (persona, user, memory, skills, artifacts), plus an
  optional per-session **project workspace**. Both roots are overridable by CLI flags.
- **Secrets.** Credentials are `${ENV}` references resolved at load; the loader never writes
  resolved values back to disk.

## Consequences

**Positive**

- Misconfiguration fails loudly and early, with the offending field identified.
- Provider/transport selection is traceable from config to the constructed adapter (A3).
- Config is unambiguous on disk and safe to commit without secrets.

**Negative / accepted costs**

- Strict validation rejects files that "sort of" work; migration is explicit rather than silent.
- The `${VAR}` mechanism intentionally supports references only, not shell-style defaults.

## Alternatives considered

- **Untyped dict config with runtime lookups.** Rejected: A4/A3 violations; errors surface late
  and provider selection becomes untraceable.
- **Silent recovery from invalid files.** Rejected: hides real breakage and can weaken security.
- **Writing resolved secrets back to the config file.** Rejected: leaks credentials to disk.