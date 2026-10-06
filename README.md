# newbot

**A self-hosted, provider-agnostic AI agent runtime.**

newbot is a small Python runtime that turns inbound messages into model-driven turns with
tool access, durable memory, and scheduled work, then returns replies over whichever
transport you use — terminal, a local web workbench, or a chat connector. The Python runtime
owns execution and security policy; every user-facing surface is a thin adapter.

> **Status: early development (`v0.0.1`).** The architecture is fixed and a full first
> implementation exists, but the project is not published to a package index yet and the
> command surface may still change. Start with [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md).

## Highlights

- **One runtime, thin clients** — terminal, HTTP/WS workbench, and chat connectors share the
  same execution core; policy never lives in a client.
- **Provider-agnostic** — any OpenAI-compatible chat-completions endpoint works
  (hosted APIs or local servers); switching providers is configuration, not code.
- **Tools for real work** — read/write/edit/list files, apply patches, run shell commands,
  fetch web pages, search the web (DuckDuckGo), schedule cron jobs, call MCP servers, use
  skills, delegate to subagents, and inspect the runtime itself.
- **Two-tier memory** — near-term session replay plus long-term durable files; a consolidation
  step summarizes compacted turns and a curation step folds them into durable knowledge.
  Every curation change-set is versioned and can be inspected or restored.
- **Safe at the boundaries** — workspace containment for paths, SSRF guards for outbound HTTP,
  optional OS-level shell sandboxing, and token/access control for the host.
- **Typed, fail-fast configuration** — TOML config with `${ENV}` secret references; invalid
  files fail loudly at startup instead of being silently repaired.

## Install

Prerequisites: Python 3.11 or newer.

```bash
# from a checkout of this repository
python -m venv .venv

# Windows PowerShell
.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate

python -m pip install -e .
```

Verify:

```bash
newbot --version
```

## Quick start

1. Create the default config and workspace:

   ```bash
   newbot init
   ```

2. Export the API key referenced by the config (the default template references
   `NEWBOT_API_KEY`), then edit the config to point at your endpoint and model.

3. Run one turn:

   ```bash
   newbot run -m "Hello!"
   ```

4. Or start an interactive terminal session (run with no command):

   ```bash
   newbot
   ```

5. Start the long-running host (web workbench, scheduler, enabled connectors):

   ```bash
   newbot serve
   ```

   Then open the workbench at `http://127.0.0.1:8787` (default; configurable under
   `[server]` in the config).

## Commands

| Command | Purpose |
| --- | --- |
| `newbot run -m "..."` | Run one turn and print the reply. |
| `newbot` | Interactive terminal session (persistent history). |
| `newbot init` | Create config and workspace defaults (never overwrites an existing config). |
| `newbot status` | Show resolved configuration without calling the model. |
| `newbot serve` | Run the long-lived host: workbench, connectors, and scheduled maintenance. |
| `newbot compact [--keep-recent N]` | Summarize a session's older history into a checkpoint. |
| `newbot curate` | Fold new memory summaries into durable files. |
| `newbot trigger <id> [message]` | Queue a local trigger delivery for the host (reads stdin when message omitted). |
| `newbot memory log` | List recorded durable-memory versions. |
| `newbot memory restore <version>` | Write a recorded version back. |
| `newbot memory revert-set <change-set>` | Undo one curation change-set. |

Global option `--config <path>` selects a config file; run `newbot <command> --help` for
per-command options. Inside an interactive session, `/help` lists the slash commands
(`/compact`, `/curate`, `/new`, `/stop`, `/exit`).

## Configuration

The config file is TOML. Default locations:

| Platform | Path |
| --- | --- |
| Windows | `%APPDATA%\newbot\config.toml` |
| Linux / macOS | `~/.config/newbot/config.toml` |

Set `NEWBOT_CONFIG_DIR` to override the directory. The agent workspace (durable files,
memory, artifacts) is configured separately and can also be created via `newbot init
--workspace <dir>`.

Minimal config created by `newbot init`:

```toml
# newbot configuration. Secrets stay as ${ENV} references; none are written here.
[provider]
baseUrl = "https://api.openai.com/v1"
apiKey = "${NEWBOT_API_KEY}"

[agent]
model = "gpt-4o-mini"
workspace = "/path/to/workspace"
```

A missing `${VAR}` or an invalid file raises a located load error; defaults are created only
when the config file is absent.

## Architecture

newbot follows a hexagonal (ports-and-adapters) design with strict inward dependencies:

```
domain ← ports ← core ← adapters ← app ← cli
                  ▲
                policy
```

- `domain` — pure value types and typed errors, no dependencies.
- `ports` — interfaces the core requires.
- `core` — small execution path: turn engine, reasoning loop, context assembly, delegation.
- `policy` — security guards (workspace, network, sandbox, access, redaction).
- `adapters` — concrete providers, transports, and stores.
- `app` / `cli` — composition root and process entry.

Read more:

- [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) — full design, module boundaries, and
  per-module contracts.
- [docs/ROADMAP.md](./docs/ROADMAP.md) — phased implementation plan.
- [docs/ADR/](./docs/ADR/README.md) — architecture decision records.

> Files under [`docs/reference/`](./docs/reference/README.md) are reference material captured
> during the analysis of a comparable public project. The authoritative newbot documentation is
> `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, and `docs/ADR/`.

## Layout

```
src/newbot/
├── domain/      # pure types
├── ports/       # interface contracts
├── policy/      # security guards
├── core/        # turn engine, reasoning loop, context, delegation
├── session/     # session management and compaction
├── memory/      # journal, consolidation, curation
├── tools/       # tool contract, registry, built-in tools
├── config/      # schema, loader, paths
├── adapters/    # providers, transports, stores, mcp
├── extensions/  # skills and plugins
├── app/         # composition and lifecycle
└── cli/         # argument parsing and entry point
```

## Development

Run the checks by the surface you change:

```bash
# tests (unit / integration / e2e)
python -m pytest

# lint and types
python -m ruff check src tests
python -m mypy src/newbot
```

Before contributing, read [AGENTS.md](./AGENTS.md) for the engineering rules and the
detailed guidance under [.agent/](./.agent/) (design, simplification, security, workflow).
