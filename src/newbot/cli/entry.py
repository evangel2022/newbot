"""Parse arguments and dispatch to the app."""

from __future__ import annotations

import argparse
import asyncio
import io
import sys
from collections.abc import Sequence
from pathlib import Path

from newbot import __version__
from newbot.adapters.providers.registry import ProviderFactory, build_provider
from newbot.app.lifecycle import run_once
from newbot.config.loader import load_settings
from newbot.domain.errors import ConfigLoadError, NewbotError


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="newbot", description="A self-hosted, provider-agnostic agent runtime."
    )
    parser.add_argument("--version", action="version", version=f"newbot {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="run one turn and print the reply")
    run.add_argument("-m", "--message", required=True, help="the message to send")
    run.add_argument("--config", type=Path, default=None, help="path to config.toml")
    return parser


def main(
    argv: Sequence[str] | None = None, *, provider_factory: ProviderFactory = build_provider
) -> int:
    """Parse arguments and run the requested command."""
    _configure_console()
    args = _build_parser().parse_args(argv)
    message = str(args.message)
    if not message.strip():
        print("error: message must not be empty", file=sys.stderr)
        return 2
    try:
        settings = load_settings(args.config)
    except ConfigLoadError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        return asyncio.run(
            run_once(settings, message, provider_factory=provider_factory)
        )
    except NewbotError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="replace")
