"""Streaming provider for OpenAI-compatible ``/chat/completions`` endpoints."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import TypedDict

import httpx
from pydantic import BaseModel, ConfigDict

from newbot.config.schema import ProviderSettings
from newbot.domain.errors import ProviderError
from newbot.domain.message import Message, Role
from newbot.domain.provider import Completed, ModelRequest, StreamEvent, TextDelta
from newbot.domain.tool import ToolCall

_STREAM_TIMEOUT = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0)
_MAX_ERROR_BODY = 500
_DATA_PREFIX = "data:"
_DONE = "[DONE]"


class _WireToolFunction(TypedDict):
    name: str
    description: str
    parameters: Mapping[str, object]


class _WireTool(TypedDict):
    type: str
    function: _WireToolFunction


class _WireToolCallFunction(TypedDict):
    name: str
    arguments: str


class _WireToolCall(TypedDict):
    id: str
    type: str
    function: _WireToolCallFunction


class _WireMessage(TypedDict, total=False):
    role: str
    content: str | None
    tool_calls: list[_WireToolCall]
    tool_call_id: str


class _FunctionDelta(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    arguments: str | None = None


class _ToolCallDelta(BaseModel):
    model_config = ConfigDict(extra="ignore")

    index: int
    id: str | None = None
    function: _FunctionDelta | None = None


class _Delta(BaseModel):
    model_config = ConfigDict(extra="ignore")

    content: str | None = None
    tool_calls: list[_ToolCallDelta] = []


class _Choice(BaseModel):
    model_config = ConfigDict(extra="ignore")

    delta: _Delta = _Delta()


class _Chunk(BaseModel):
    model_config = ConfigDict(extra="ignore")

    choices: list[_Choice] = []

    def first_delta(self) -> _Delta | None:
        if not self.choices:
            return None
        return self.choices[0].delta


class _CallAccumulator:
    def __init__(self) -> None:
        self.id = ""
        self.name = ""
        self.arguments = ""


class OpenAICompatibleProvider:
    """Streams replies from any OpenAI-compatible chat-completions endpoint."""

    def __init__(
        self, settings: ProviderSettings, *, client: httpx.AsyncClient | None = None
    ) -> None:
        self._settings = settings
        self._client = (
            client if client is not None else httpx.AsyncClient(timeout=_STREAM_TIMEOUT)
        )
        self._owns_client = client is None

    def stream(self, request: ModelRequest) -> AsyncIterator[StreamEvent]:
        return self._stream(request)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _stream(self, request: ModelRequest) -> AsyncIterator[StreamEvent]:
        url = f"{self._settings.base_url.rstrip('/')}/chat/completions"
        payload: dict[str, object] = {
            "model": request.model,
            "messages": _encode_messages(request),
            "stream": True,
        }
        if request.tools:
            payload["tools"] = _encode_tools(request)
        if self._settings.max_tokens is not None:
            payload["max_tokens"] = self._settings.max_tokens
        headers = {"Accept": "text/event-stream"}
        if self._settings.api_key:
            headers["Authorization"] = f"Bearer {self._settings.api_key}"
        parts: list[str] = []
        calls: dict[int, _CallAccumulator] = {}
        try:
            async with self._client.stream(
                "POST", url, json=payload, headers=headers
            ) as response:
                if response.status_code != httpx.codes.OK:
                    body = (await response.aread()).decode("utf-8", "replace")
                    raise ProviderError(
                        f"provider returned HTTP {response.status_code}: {_bounded(body)}"
                    )
                async for line in response.aiter_lines():
                    data = _sse_data(line)
                    if data is None:
                        continue
                    if data == _DONE:
                        break
                    delta = _parse_chunk(data).first_delta()
                    if delta is None:
                        continue
                    if delta.content:
                        parts.append(delta.content)
                        yield TextDelta(text=delta.content)
                    for tool_delta in delta.tool_calls:
                        _accumulate(calls, tool_delta)
        except httpx.HTTPError as exc:
            raise ProviderError(f"provider request failed: {exc}") from exc
        yield Completed(
            message=Message(
                role=Role.ASSISTANT,
                content="".join(parts),
                tool_calls=tuple(
                    ToolCall(id=acc.id, name=acc.name, arguments=acc.arguments)
                    for _, acc in sorted(calls.items())
                ),
            )
        )


def _encode_messages(request: ModelRequest) -> list[_WireMessage]:
    messages: list[_WireMessage] = []
    if request.system:
        messages.append({"role": Role.SYSTEM.value, "content": request.system})
    for message in request.messages:
        wire: _WireMessage = {"role": message.role.value, "content": message.content}
        if message.tool_calls:
            wire["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments},
                }
                for call in message.tool_calls
            ]
            if not message.content:
                wire["content"] = None
        if message.tool_call_id is not None:
            wire["tool_call_id"] = message.tool_call_id
        messages.append(wire)
    return messages


def _encode_tools(request: ModelRequest) -> list[_WireTool]:
    return [
        {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            },
        }
        for spec in request.tools
    ]


def _accumulate(calls: dict[int, _CallAccumulator], delta: _ToolCallDelta) -> None:
    accumulator = calls.setdefault(delta.index, _CallAccumulator())
    if delta.id:
        accumulator.id = delta.id
    if delta.function is not None:
        if delta.function.name:
            accumulator.name += delta.function.name
        if delta.function.arguments:
            accumulator.arguments += delta.function.arguments


def _sse_data(line: str) -> str | None:
    if not line.startswith(_DATA_PREFIX):
        return None
    return line[len(_DATA_PREFIX) :].strip()


def _parse_chunk(data: str) -> _Chunk:
    try:
        return _Chunk.model_validate_json(data)
    except ValueError as exc:
        raise ProviderError(f"malformed provider chunk: {_bounded(data)}") from exc


def _bounded(text: str) -> str:
    text = text.strip()
    if len(text) <= _MAX_ERROR_BODY:
        return text
    return text[:_MAX_ERROR_BODY] + "...[truncated]"
