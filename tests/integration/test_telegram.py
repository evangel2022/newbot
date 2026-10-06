"""Telegram channel tests over a mocked HTTP transport."""

from __future__ import annotations

import io
import json
from collections.abc import Callable

import httpx
import pytest

from newbot.adapters.transports.connectors.telegram import (
    TelegramConnector,
    parse_update,
)
from newbot.domain.envelope import InboundEnvelope, OutboundEnvelope
from newbot.domain.errors import TransportError
from newbot.domain.turn import TurnStatus


class _StopPolling(Exception):
    """Ends a polling loop from inside the transport stub."""


def _update(update_id: int, text: str, *, chat_id: int = 7) -> dict[str, object]:
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "chat": {"id": chat_id, "type": "private"},
            "text": text,
        },
    }


def _client(
    handler: Callable[[httpx.Request], httpx.Response],
) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _ok(result: object) -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "result": result})


def test_parse_update_maps_a_text_message_to_an_envelope() -> None:
    update = parse_update(_update(5, "hello"))

    assert update.update_id == 5
    assert update.envelope == InboundEnvelope(
        transport="telegram", conversation_id="7", text="hello"
    )


def test_parse_update_allows_every_chat_without_an_allowlist() -> None:
    update = parse_update(_update(1, "hi", chat_id=99))

    assert update.envelope is not None
    assert update.envelope.conversation_id == "99"


@pytest.mark.parametrize(
    "payload",
    [
        {"update_id": 1},
        {"update_id": 1, "message": {"chat": {"id": 7}}},
        {"update_id": 1, "message": {"chat": {"id": 7}, "text": ""}},
        _update(1, "hello", chat_id=99),
    ],
    ids=["no-message", "no-text", "empty-text", "disallowed-chat"],
)
def test_parse_update_ignores_updates_it_should_not_run(
    payload: dict[str, object],
) -> None:
    update = parse_update(payload, allowed_chat_ids=[7])

    assert update.envelope is None


def test_parse_update_rejects_an_update_without_an_id() -> None:
    with pytest.raises(TransportError):
        parse_update({"message": {"chat": {"id": 7}, "text": "hi"}})


async def test_deliver_sends_the_reply_to_its_chat() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _ok({"message_id": 9})

    connector = TelegramConnector(token="t", client=_client(handler))
    await connector.deliver(
        OutboundEnvelope(transport="telegram", conversation_id="-7", text="hi")
    )

    assert captured[0].url.path == "/bott/sendMessage"
    assert json.loads(captured[0].content) == {"chat_id": -7, "text": "hi"}


async def test_deliver_rejects_a_conversation_that_is_not_a_chat_id() -> None:
    connector = TelegramConnector(
        token="t", client=_client(lambda request: _ok({"message_id": 1}))
    )

    with pytest.raises(TransportError):
        await connector.deliver(
            OutboundEnvelope(transport="telegram", conversation_id="ops", text="hi")
        )


async def test_a_failed_api_call_is_a_transport_error() -> None:
    connector = TelegramConnector(
        token="t",
        client=_client(
            lambda request: httpx.Response(
                401, json={"ok": False, "description": "Unauthorized"}
            )
        ),
    )

    with pytest.raises(TransportError) as info:
        await connector.deliver(
            OutboundEnvelope(transport="telegram", conversation_id="1", text="hi")
        )

    assert "401" in str(info.value)
    assert "Unauthorized" in str(info.value)


async def test_request_errors_do_not_leak_the_bot_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot connect to {request.url}")

    connector = TelegramConnector(token="secret-token", client=_client(handler))

    with pytest.raises(TransportError) as info:
        await connector.deliver(
            OutboundEnvelope(transport="telegram", conversation_id="1", text="hi")
        )

    assert "secret-token" not in str(info.value)


async def test_run_confirms_the_backlog_then_submits_new_updates() -> None:
    submitted: list[InboundEnvelope] = []
    payloads: list[dict[str, object]] = []
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        payloads.append(json.loads(request.content))
        if calls == 1:
            return _ok([_update(1, "old")])
        if calls == 2:
            return _ok([_update(2, "new")])
        raise _StopPolling

    async def submit(envelope: InboundEnvelope) -> TurnStatus:
        submitted.append(envelope)
        return TurnStatus.COMPLETED

    connector = TelegramConnector(
        token="t", poll_timeout_seconds=0.01, client=_client(handler)
    )
    with pytest.raises(_StopPolling):
        await connector.run(submit)

    assert [envelope.text for envelope in submitted] == ["new"]
    assert "offset" not in payloads[0]
    assert payloads[1]["offset"] == 2
    assert payloads[1]["timeout"] == 0.01


async def test_run_keeps_polling_after_a_failed_turn() -> None:
    submitted: list[InboundEnvelope] = []
    stderr = io.StringIO()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return _ok([])
        if calls == 2:
            return _ok([_update(1, "first"), _update(2, "second")])
        raise _StopPolling

    async def submit(envelope: InboundEnvelope) -> TurnStatus:
        submitted.append(envelope)
        if envelope.text == "first":
            raise TransportError("subscriber exploded")
        return TurnStatus.COMPLETED

    connector = TelegramConnector(
        token="t",
        poll_timeout_seconds=0.01,
        client=_client(handler),
        stderr=stderr,
    )
    with pytest.raises(_StopPolling):
        await connector.run(submit)

    assert [envelope.text for envelope in submitted] == ["first", "second"]
    assert "telegram turn failed" in stderr.getvalue()
