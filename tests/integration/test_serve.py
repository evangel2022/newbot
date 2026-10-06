"""Integration tests for the long-running serve host."""

from __future__ import annotations

import asyncio
import io
import json
import re
from pathlib import Path

import httpx
import pytest

from newbot.adapters.stores.jsonl_journal import JsonlJournal
from newbot.adapters.transports.http_ws import WORKBENCH_TRANSPORT_ID
from newbot.app.bootstrap import build_sessions, build_trigger_queue
from newbot.app.lifecycle import run_serve
from newbot.config.schema import Settings
from newbot.domain.session import SessionKey
from newbot.memory.layout import MemoryLayout
from support import FakeProvider, reply_events


def _settings(
    tmp_path: Path,
    *,
    interval: float | None,
    turns: list[dict[str, object]] | None = None,
    triggers: list[dict[str, object]] | None = None,
    trigger_poll: float = 1.0,
    heartbeat: dict[str, object] | None = None,
) -> Settings:
    return Settings.model_validate(
        {
            "provider": {"base_url": "https://api.example.com/v1", "api_key": "k"},
            "agent": {"model": "gpt-test", "workspace": str(tmp_path / "ws")},
            "sessions": {"dir": str(tmp_path / "sessions")},
            "schedule": {
                "curation_interval_seconds": interval,
                "turns": turns or [],
            },
            "triggers": {
                "dir": str(tmp_path / "triggers"),
                "poll_interval_seconds": trigger_poll,
                "items": triggers or [],
            },
            "heartbeat": heartbeat or {},
            "server": {"port": 0},
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


async def test_serve_exposes_a_loopback_health_endpoint(tmp_path: Path) -> None:
    settings = _settings(tmp_path, interval=None)
    stdout = io.StringIO()

    task = asyncio.create_task(
        run_serve(
            settings,
            provider_factory=lambda _settings: FakeProvider(reply_events("x")),
            stdout=stdout,
            stderr=io.StringIO(),
        )
    )
    try:
        url = await _wait_for_health_url(stdout)
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{url}/health")
    finally:
        task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_serve_runs_a_scheduled_turn_in_its_bound_conversation(
    tmp_path: Path,
) -> None:
    settings = _settings(
        tmp_path,
        interval=None,
        turns=[
            {
                "every_seconds": 0.01,
                "conversation": "ops",
                "prompt": "do the thing",
            }
        ],
    )
    provider = FakeProvider(reply_events("scheduled reply"))

    task = asyncio.create_task(
        run_serve(
            settings,
            provider_factory=lambda _settings: provider,
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )
    )
    try:
        await _wait_for_reply(settings, "ops", "scheduled reply")
    finally:
        task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert provider.closed is True
    assert any(
        message.content == "do the thing" for message in provider.requests[0].messages
    )


async def test_serve_delivers_a_queued_trigger_to_its_conversation(
    tmp_path: Path,
) -> None:
    settings = _settings(
        tmp_path,
        interval=None,
        triggers=[{"id": "ci", "conversation": "ops"}],
        trigger_poll=0.01,
    )
    build_trigger_queue(settings).enqueue("ci", "ops", "build failed")
    provider = FakeProvider(reply_events("trigger reply"))

    task = asyncio.create_task(
        run_serve(
            settings,
            provider_factory=lambda _settings: provider,
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )
    )
    try:
        await _wait_for_reply(settings, "ops", "trigger reply")
    finally:
        task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert provider.closed is True
    assert any(
        message.content == "build failed" for message in provider.requests[0].messages
    )
    assert build_trigger_queue(settings).claim() == ()


async def test_serve_runs_heartbeat_tasks_in_its_conversation(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        interval=None,
        heartbeat={
            "enabled": True,
            "interval_seconds": 0.01,
            "conversation": "checks",
        },
    )
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "HEARTBEAT.md").write_text(
        "## Active Tasks\n\n- Watch the build\n", encoding="utf-8"
    )
    provider = FakeProvider(reply_events("heartbeat reply"))

    task = asyncio.create_task(
        run_serve(
            settings,
            provider_factory=lambda _settings: provider,
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )
    )
    try:
        await _wait_for_reply(settings, "checks", "heartbeat reply")
    finally:
        task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert provider.closed is True
    assert any(
        "Watch the build" in message.content
        for message in provider.requests[0].messages
    )


@pytest.mark.parametrize(
    "content",
    [None, "# Heartbeat\n", "## Active Tasks\n\nNothing to do.\n", "## Done\n- old\n"],
    ids=["absent", "no-section", "empty-section", "other-section"],
)
async def test_serve_heartbeat_stays_quiet_without_active_tasks(
    tmp_path: Path, content: str | None
) -> None:
    settings = _settings(
        tmp_path,
        interval=None,
        heartbeat={"enabled": True, "interval_seconds": 0.01},
    )
    workspace = tmp_path / "ws"
    workspace.mkdir()
    if content is not None:
        (workspace / "HEARTBEAT.md").write_text(content, encoding="utf-8")
    provider = FakeProvider(reply_events("unexpected"))

    task = asyncio.create_task(
        run_serve(
            settings,
            provider_factory=lambda _settings: provider,
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )
    )
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert provider.requests == []


async def test_serve_heartbeat_is_opt_in(tmp_path: Path) -> None:
    settings = _settings(tmp_path, interval=None)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "HEARTBEAT.md").write_text(
        "## Active Tasks\n- Watch the build\n", encoding="utf-8"
    )
    provider = FakeProvider(reply_events("unexpected"))

    task = asyncio.create_task(
        run_serve(
            settings,
            provider_factory=lambda _settings: provider,
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )
    )
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert provider.requests == []


async def _wait_for_health_url(stdout: io.StringIO, *, timeout: float = 2.0) -> str:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        match = re.search(r"health (http://\S+)", stdout.getvalue())
        if match is not None:
            return match.group(1)
        if loop.time() > deadline:
            raise TimeoutError("health URL was not announced")
        await asyncio.sleep(0.01)


async def _wait_for_file(path: Path, *, timeout: float = 2.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not path.is_file():
        if loop.time() > deadline:
            raise TimeoutError(f"{path} was not created")
        await asyncio.sleep(0.01)


async def _wait_for_reply(
    settings: Settings, conversation: str, expected: str, *, timeout: float = 2.0
) -> None:
    sessions = build_sessions(settings)
    key = SessionKey(transport=WORKBENCH_TRANSPORT_ID, conversation=conversation)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        history = await sessions.history(key)
        if any(message.content == expected for message in history):
            return
        if loop.time() > deadline:
            raise TimeoutError(f"scheduled reply {expected!r} was not recorded")
        await asyncio.sleep(0.01)
