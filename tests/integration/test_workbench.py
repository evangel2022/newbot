"""Integration tests for the loopback workbench transport."""

from __future__ import annotations

import asyncio
import io
import re
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from newbot.app.lifecycle import run_serve
from newbot.config.schema import Settings
from newbot.domain.message import Message, Role
from newbot.domain.provider import Completed, ModelRequest, StreamEvent, TextDelta
from newbot.ports.provider import ProviderPort
from support import FakeProvider, reply_events

_TOKEN = "s3cret-token"


class _ScriptedProvider:
    """Yields one distinct reply per call, pausing so calls can interleave."""

    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)

    def stream(self, request: ModelRequest) -> AsyncIterator[StreamEvent]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[StreamEvent]:
        reply = self._replies.pop(0)
        await asyncio.sleep(0.01)
        yield TextDelta(text=reply)
        yield Completed(message=Message(role=Role.ASSISTANT, content=reply))

    async def aclose(self) -> None:
        return None


def _settings(tmp_path: Path, *, token: str | None) -> Settings:
    return Settings.model_validate(
        {
            "provider": {"base_url": "https://api.example.com/v1", "api_key": "k"},
            "agent": {"model": "gpt-test", "workspace": str(tmp_path / "ws")},
            "sessions": {"dir": str(tmp_path / "sessions")},
            "server": {"port": 0, "token": token},
        }
    )


def _serve(
    settings: Settings,
    stdout: io.StringIO,
    provider: ProviderPort | None = None,
) -> asyncio.Task[int]:
    chosen: ProviderPort = (
        provider if provider is not None else FakeProvider(reply_events("pong"))
    )
    return asyncio.create_task(
        run_serve(
            settings,
            provider_factory=lambda _settings: chosen,
            stdout=stdout,
            stderr=io.StringIO(),
        )
    )


async def test_workbench_negotiates_capabilities_and_answers_a_turn(
    tmp_path: Path,
) -> None:
    stdout = io.StringIO()
    task = _serve(_settings(tmp_path, token=_TOKEN), stdout)
    try:
        url = await _wait_for_url(stdout)
        async with httpx.AsyncClient() as client:
            health = await client.get(f"{url}/health")
            capabilities = await client.get(f"{url}/capabilities")
            unauthorized = await client.post(f"{url}/messages", json={"text": "hi"})
            reply = await client.post(
                f"{url}/messages",
                json={"text": "hi", "capabilities": ["future-thing"]},
                headers={"Authorization": f"Bearer {_TOKEN}"},
            )
    finally:
        task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert health.status_code == 200
    assert capabilities.status_code == 200
    assert capabilities.json() == {"protocol": 1, "capabilities": ["chat"]}
    assert unauthorized.status_code == 401
    assert reply.status_code == 200
    assert reply.json() == {"reply": "pong"}


async def test_workbench_rejects_an_incompatible_protocol(tmp_path: Path) -> None:
    stdout = io.StringIO()
    task = _serve(_settings(tmp_path, token=_TOKEN), stdout)
    try:
        url = await _wait_for_url(stdout)
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{url}/messages",
                json={"text": "hi", "protocol": 99},
                headers={"Authorization": f"Bearer {_TOKEN}"},
            )
    finally:
        task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert response.status_code == 400


async def test_workbench_refuses_mutations_without_a_token(tmp_path: Path) -> None:
    stdout = io.StringIO()
    task = _serve(_settings(tmp_path, token=None), stdout)
    try:
        url = await _wait_for_url(stdout)
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{url}/messages", json={"text": "hi"})
    finally:
        task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert response.status_code == 403


async def test_workbench_correlates_concurrent_turns_per_conversation(
    tmp_path: Path,
) -> None:
    stdout = io.StringIO()
    provider = _ScriptedProvider(["first", "second"])
    task = _serve(_settings(tmp_path, token=_TOKEN), stdout, provider)
    try:
        url = await _wait_for_url(stdout)
        headers = {"Authorization": f"Bearer {_TOKEN}"}
        async with httpx.AsyncClient(timeout=10.0) as client:
            responses = await asyncio.gather(
                client.post(
                    f"{url}/messages",
                    json={"conversation": "shared", "text": "one"},
                    headers=headers,
                ),
                client.post(
                    f"{url}/messages",
                    json={"conversation": "shared", "text": "two"},
                    headers=headers,
                ),
            )
    finally:
        task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert [response.status_code for response in responses] == [200, 200]
    assert sorted(response.json()["reply"] for response in responses) == [
        "first",
        "second",
    ]


async def _wait_for_url(stdout: io.StringIO, *, timeout: float = 5.0) -> str:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        match = re.search(r"health (http://\S+)", stdout.getvalue())
        if match is not None:
            return match.group(1)
        if loop.time() > deadline:
            raise TimeoutError("workbench URL was not announced")
        await asyncio.sleep(0.01)
