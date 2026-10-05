"""Parse arguments and dispatch to the app."""

from __future__ import annotations

import argparse
import asyncio
import io
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from newbot import __version__
from newbot.adapters.providers.registry import ProviderFactory, build_provider
from newbot.app.lifecycle import (
    run_compact,
    run_curate,
    run_interactive,
    run_memory_log,
    run_memory_restore,
    run_once,
)
from newbot.config.init import InitOutcome, initialize
from newbot.config.loader import load_settings
from newbot.config.paths import config_path
from newbot.config.schema import Settings
from newbot.domain.errors import ConfigLoadError, NewbotError

_CONFIG_HELP = "path to config.toml"


def _non_negative(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid int value: {value!r}") from None
    if number < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return number


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="newbot",
        description="A self-hosted, provider-agnostic agent runtime.",
        epilog="Run without a command to start an interactive session.",
    )
    parser.add_argument("--version", action="version", version=f"newbot {__version__}")
    parser.add_argument("--config", type=Path, default=None, help=_CONFIG_HELP)
    subparsers = parser.add_subparsers(dest="command")
    run = subparsers.add_parser("run", help="run one turn and print the reply")
    run.add_argument("-m", "--message", required=True, help="the message to send")
    run.add_argument(
        "--config", type=Path, default=argparse.SUPPRESS, help=_CONFIG_HELP
    )
    init = subparsers.add_parser("init", help="create config and workspace defaults")
    init.add_argument(
        "--config", type=Path, default=argparse.SUPPRESS, help=_CONFIG_HELP
    )
    init.add_argument(
        "--workspace", type=Path, default=None, help="agent workspace directory"
    )
    compact = subparsers.add_parser(
        "compact", help="summarize a session's older history"
    )
    compact.add_argument(
        "--config", type=Path, default=argparse.SUPPRESS, help=_CONFIG_HELP
    )
    compact.add_argument(
        "--keep-recent",
        type=_non_negative,
        default=8,
        help="recent messages to keep verbatim",
    )
    curate = subparsers.add_parser(
        "curate", help="fold new memory summaries into durable files"
    )
    curate.add_argument(
        "--config", type=Path, default=argparse.SUPPRESS, help=_CONFIG_HELP
    )
    memory = subparsers.add_parser(
        "memory", help="inspect and restore durable memory versions"
    )
    memory.add_argument(
        "--config", type=Path, default=argparse.SUPPRESS, help=_CONFIG_HELP
    )
    memory_commands = memory.add_subparsers(dest="memory_command", required=True)
    memory_log = memory_commands.add_parser("log", help="list recorded versions")
    memory_log.add_argument(
        "--config", type=Path, default=argparse.SUPPRESS, help=_CONFIG_HELP
    )
    memory_restore = memory_commands.add_parser(
        "restore", help="write a recorded version back"
    )
    memory_restore.add_argument("version", help="the version id to restore")
    memory_restore.add_argument(
        "--config", type=Path, default=argparse.SUPPRESS, help=_CONFIG_HELP
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    provider_factory: ProviderFactory = build_provider,
    stdin: TextIO | None = None,
) -> int:
    """Parse arguments and dispatch to the requested command."""
    _configure_console()
    args = _build_parser().parse_args(argv)
    if args.command == "init":
        return _init_command(args)
    if args.command == "run" and not str(args.message).strip():
        print("error: message must not be empty", file=sys.stderr)
        return 2
    try:
        settings = load_settings(args.config)
    except ConfigLoadError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        if args.command == "run":
            return asyncio.run(
                run_once(settings, str(args.message), provider_factory=provider_factory)
            )
        if args.command == "compact":
            return asyncio.run(
                run_compact(
                    settings,
                    keep_recent=args.keep_recent,
                    provider_factory=provider_factory,
                )
            )
        if args.command == "curate":
            return asyncio.run(run_curate(settings, provider_factory=provider_factory))
        if args.command == "memory":
            return _memory_command(args, settings)
        return asyncio.run(
            run_interactive(
                settings,
                stdin=sys.stdin if stdin is None else stdin,
                provider_factory=provider_factory,
            )
        )
    except NewbotError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


def _init_command(args: argparse.Namespace) -> int:
    config_file = (args.config if args.config is not None else config_path()).resolve()
    workspace = (args.workspace or config_file.parent / "workspace").resolve()
    try:
        outcome = initialize(config_file, workspace)
    except ConfigLoadError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if outcome is InitOutcome.EXISTS:
        print(f"config already exists, not modified: {config_file}")
        return 0
    print(f"created config: {config_file}")
    print(f"created workspace: {workspace}")
    return 0


def _memory_command(args: argparse.Namespace, settings: Settings) -> int:
    if args.memory_command == "restore":
        return asyncio.run(run_memory_restore(settings, version_id=args.version))
    return asyncio.run(run_memory_log(settings))


def _configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="replace")
