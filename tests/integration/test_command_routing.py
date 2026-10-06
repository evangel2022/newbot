"""Commands are routed through the built runtime's inbound handler."""

from __future__ import annotations

import io
from pathlib import Path

from newbot.app.bootstrap import Runtime, build_runtime
from newbot.config.schema import Settings
from newbot.domain.envelope import InboundEnvelope
from newbot.domain.message import Message, Role
from newbot.domain.session import SessionKey
from newbot.domain.turn import TurnStatus
from support import CollectingTransport, FakeProvider, reply_events

KEY = SessionKey("test", "ops")


async def _runtime(tmp_path: Path) -> Runtime:
    settings = Settings.model_validate(
        {
            "provider": {"baseUrl": "https://api.example.com/v1", "apiKey": "k"},
            "agent": {"model": "m", "workspace": str(tmp_path / "ws")},
            "sessions": {"dir": str(tmp_path / "sessions")},
        }
    )
    return await build_runtime(
        settings,
        provider_factory=lambda _settings: FakeProvider(reply_events("unused")),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )


async def test_the_built_runtime_routes_stop(tmp_path: Path) -> None:
    runtime = await _runtime(tmp_path)
    transport = CollectingTransport()
    runtime.hub.register_transport(transport)
    try:
        status = await runtime.hub.submit(
            InboundEnvelope(transport="test", conversation_id="ops", text="/stop")
        )
    finally:
        await runtime.aclose()

    assert status is TurnStatus.COMPLETED
    assert [envelope.text for envelope in transport.delivered] == [
        "no running subagent tasks"
    ]


async def test_the_built_runtime_routes_new(tmp_path: Path) -> None:
    runtime = await _runtime(tmp_path)
    transport = CollectingTransport()
    runtime.hub.register_transport(transport)
    await runtime.sessions.record(KEY, (Message(role=Role.USER, content="hi"),))
    try:
        status = await runtime.hub.submit(
            InboundEnvelope(transport="test", conversation_id="ops", text="/new")
        )
    finally:
        await runtime.aclose()

    assert status is TurnStatus.COMPLETED
    assert [envelope.text for envelope in transport.delivered] == [
        "started a new conversation"
    ]
    assert await runtime.sessions.history(KEY) == ()
