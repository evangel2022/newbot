"""Integration tests for the long-running serve host."""

from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path

import pytest

from newbot.adapters.stores.jsonl_journal import JsonlJournal
from newbot.app.lifecycle import run_serve
from newbot.config.schema import Settings
from newbot.memory.layout import MemoryLayout
from support import FakeProvider, reply_events


def _settings(tmp_path: Path, *, interval: float | None) -> Settings:
    return Settings.model_validate(
        {
            "provider": {"base_url": "https://api.example.com/v1", "api_key": "k"},
            "agent": {"model": "gpt-test", "workspace": str(tmp_path / "ws")},
            "sessions": {"dir": str(tmp_path / "sessions")},
            "schedule": {"curation_interval_seconds": interval},
        }
    )


async def test_serve_runs_scheduled_curation_until_cancelled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEWBOT_CONFIG_DIR", str(tmp_path / "config"))
    settings = _settings(tmp_path, interval=0.01)
    layout = MemoryLayout(tmp_path / "ws")
    await JsonlJournal(layout.journal).append("summary")
    plan = json.dumps(
        {"files": [{"path": "memory/knowledge.md", "content": "- fact\n"}]}
    )
    provider = FakeProvider(reply_events(plan))
    stdout = io.StringIO()

    task = asyncio.create_task(
        run_serve(
            settings,
            provider_factory=lambda _settings: provider,
            stdout=stdout,
            stderr=io.StringIO(),
        )
    )
    try:
        await _wait_for_file(layout.knowledge)
    finally:
        task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert "serving" in stdout.getvalue()
    assert layout.knowledge.read_text(encoding="utf-8") == "- fact\n"
    assert provider.closed is True


async def test_serve_without_a_schedule_idles_until_cancelled(tmp_path: Path) -> None:
    settings = _settings(tmp_path, interval=None)

    task = asyncio.create_task(
        run_serve(
            settings,
            provider_factory=lambda _settings: FakeProvider(reply_events("x")),
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )
    )
    await asyncio.sleep(0.05)

    assert not task.done()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def _wait_for_file(path: Path, *, timeout: float = 2.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not path.is_file():
        if loop.time() > deadline:
            raise TimeoutError(f"{path} was not created")
        await asyncio.sleep(0.01)
