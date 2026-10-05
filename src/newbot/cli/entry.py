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
from newbot.app.lifecycle import run_interactive, run_once
from newbot.config.loader import load_settings
from newbot.domain.errors import ConfigLoadError, NewbotError

_CONFIG_HELP = "path to config.toml"


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
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    provider_factory: ProviderFactory = build_provider,
    stdin: TextIO | None = None,
) -> int:
    """Parse arguments and run one turn or an interactive session."""
    _configure_console()
    args = _build_parser().parse_args(argv)
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


def _configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="replace")
