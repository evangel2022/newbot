"""Provider adapter tests over a mocked HTTP transport."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from newbot.adapters.providers.openai_compatible import OpenAICompatibleProvider
from newbot.config.schema import ProviderSettings
from newbot.domain.errors import ProviderError
from newbot.domain.message import Message, Role
from newbot.domain.provider import Completed, ModelRequest, TextDelta
from newbot.domain.tool import ToolCall, ToolSpec

REQUEST = ModelRequest(
    model="gpt-test",
    system="be terse",
    messages=(Message(role=Role.USER, content="hi"),),
)

SSE_BODY = (
    'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n'
    'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n'
    "data: [DONE]\n\n"
)


def _settings() -> ProviderSettings:
    return ProviderSettings(base_url="https://api.example.com/v1", api_key="k")


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_streams_deltas_and_completes() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=SSE_BODY.encode(),
        )

    provider = OpenAICompatibleProvider(_settings(), client=_client(handler))
    events = [event async for event in provider.stream(REQUEST)]

    assert [event.text for event in events if isinstance(event, TextDelta)] == ["Hel", "lo"]
    assert isinstance(events[-1], Completed)
    assert events[-1].message.content == "Hello"

    payload = json.loads(captured[0].content)
    assert payload["model"] == "gpt-test"
    assert payload["stream"] is True
    assert payload["messages"][0] == {"role": "system", "content": "be terse"}
    assert captured[0].headers["authorization"] == "Bearer k"


async def test_non_200_response_is_a_provider_error() -> None:
    provider = OpenAICompatibleProvider(
        _settings(), client=_client(lambda request: httpx.Response(500, content=b"boom"))
    )

    with pytest.raises(ProviderError) as info:
        _ = [event async for event in provider.stream(REQUEST)]

    assert "500" in str(info.value)


async def test_malformed_chunk_is_a_provider_error() -> None:
    provider = OpenAICompatibleProvider(
        _settings(),
        client=_client(lambda request: httpx.Response(200, content=b"data: {not json}\n\n")),
    )

    with pytest.raises(ProviderError):
        _ = [event async for event in provider.stream(REQUEST)]


TOOL_SSE = (
    b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1",'
    b'"function":{"name":"read_","arguments":"{\\"pa"}}]}}]}\n\n'
    b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
    b'"function":{"name":"file","arguments":"th\\":\\"a.txt\\"}"}}]}}]}\n\n'
    b"data: [DONE]\n\n"
)


async def test_streams_tool_calls_across_chunks() -> None:
    provider = OpenAICompatibleProvider(
        _settings(),
        client=_client(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=TOOL_SSE,
            )
        ),
    )

    events = [event async for event in provider.stream(REQUEST)]

    assert isinstance(events[-1], Completed)
    calls = events[-1].message.tool_calls
    assert len(calls) == 1
    assert calls[0].id == "call_1"
    assert calls[0].name == "read_file"
    assert calls[0].arguments == '{"path":"a.txt"}'


async def test_encodes_tools_and_tool_messages() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b"data: [DONE]\n\n",
        )

    provider = OpenAICompatibleProvider(_settings(), client=_client(handler))
    request = ModelRequest(
        model="gpt-test",
        system="be terse",
        messages=(
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=(ToolCall(id="c1", name="read_file", arguments="{}"),),
            ),
            Message(role=Role.TOOL, content="data", tool_call_id="c1"),
        ),
        tools=(
            ToolSpec(name="read_file", description="read", parameters={"type": "object"}),
        ),
    )

    _ = [event async for event in provider.stream(request)]

    payload = json.loads(captured[0].content)
    assert payload["tools"][0]["function"]["name"] == "read_file"
    assert payload["messages"][1]["content"] is None
    assert payload["messages"][1]["tool_calls"][0]["id"] == "c1"
    assert payload["messages"][2] == {
        "role": "tool",
        "content": "data",
        "tool_call_id": "c1",
    }
