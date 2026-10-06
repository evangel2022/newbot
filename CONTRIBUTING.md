# Contributing to newbot

Thanks for your interest in improving newbot. This is a small, design-first project: changes
are reviewed against explicit architecture and security rules, not only for correctness.

## Before you start

1. Read [AGENTS.md](./AGENTS.md) — it defines the runtime's core boundary and the
   task-specific rule documents under [.agent/](./.agent/):

   | When working on | Read |
   | --- | --- |
   | Core boundaries, extensions, internal types | [.agent/design.md](./.agent/design.md) |
   | Refactoring, fallbacks, test selection | [.agent/simplify.md](./.agent/simplify.md) |
   | Path permissions, HTTP/MCP, shell isolation | [.agent/security.md](./.agent/security.md) |
   | Dependency setup, config, Windows, persistence | [.agent/gotchas.md](./.agent/gotchas.md) |
   | WebUI/host compatibility | [.agent/review-guide.md](./.agent/review-guide.md) |

2. For non-trivial changes, check [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) and the
   relevant [ADR](./docs/ADR/README.md) to confirm where the change belongs.

## Development setup

Prerequisites: Python 3.11 or newer.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Set the provider credential used by the default configuration:

```powershell
[Environment]::SetEnvironmentVariable('NEWBOT_API_KEY','your-key','User')
```

## Verification

Choose checks by the surface you changed — see [ADR-009](./docs/ADR/ADR-009-testing.md):

```powershell
python -m pytest
python -m ruff check src tests
python -m mypy src/newbot
```

- Do not add defensive tests for impossible internal states; each test must protect a reachable
  contract.
- Do not run a blanket code formatter; mechanical reformatting obscures history.

## Commit messages

Use Conventional Commits:

```
<type>: <short summary>
```

Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`. Keep the subject line under
~72 characters. Explain *why* in the body when the motivation is not obvious.

## Pull requests

- Keep changes focused; one logical change per PR.
- Describe what changed, why, and how it was verified.
- Confirm the relevant security boundary still holds for any change touching filesystem, shell,
  network, or transport access.
- Update docs or an ADR when a boundary or public contract changes.

## Code of conduct

Participation in this project is governed by the [Code of Conduct](./CODE_OF_CONDUCT.md). By
participating, you agree to uphold it.
