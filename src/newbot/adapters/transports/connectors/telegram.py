"""Telegram chat channel: long-poll inbound messages, send replies."""

from __future__ import annotations

import asyncio
import re
import sys
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import TextIO

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from newbot.domain.envelope import InboundEnvelope, OutboundEnvelope
from newbot.domain.errors import NewbotError, TransportError
from newbot.ports.transports import InboundHandler

TELEGRAM_TRANSPORT_ID = "telegram"

_REQUEST_SLACK_SECONDS = 10.0
_SEND_TIMEOUT_SECONDS = 30.0
_ERROR_RETRY_SECONDS = 1.0
_MAX_ERROR_CHARS = 500
_CHAT_ID = re.compile(r"-?\d{1,20}")


class _Chat(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int


class _Message(BaseModel):
    model_config = ConfigDict(extra="ignore")

    chat: _Chat
    text: str | None = None


class _Update(BaseModel):
    model_config = ConfigDict(extra="ignore")

    update_id: int
    message: _Message | None = None


class _MessageId(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message_id: int


@dataclass(frozen=True, slots=True)
class TelegramUpdate:
    """One validated update: its cursor position and, for text, its envelope."""

    update_id: int
    envelope: InboundEnvelope | None


def parse_update(
    payload: Mapping[str, object], *, allowed_chat_ids: Collection[int] = ()
) -> TelegramUpdate:
    """Validate one Telegram update at the boundary.

    Only a non-empty text message from an allowed chat becomes an envelope;
    every other update is ignored but still advances the cursor. Telegram adds
    fields over time, so unknown keys are ignored rather than rejected.
    """
    try:
        update = _Update.model_validate(payload)
    except ValidationError as exc:
        raise TransportError(f"telegram update was invalid: {exc}") from exc
    message = update.message
    if message is None or not message.text:
        return TelegramUpdate(update_id=update.update_id, envelope=None)
    if allowed_chat_ids and message.chat.id not in allowed_chat_ids:
        return TelegramUpdate(update_id=update.update_id, envelope=None)
    return TelegramUpdate(
        update_id=update.update_id,
        envelope=InboundEnvelope(
            transport=TELEGRAM_TRANSPORT_ID,
            conversation_id=str(message.chat.id),
            text=message.text,
        ),
    )


class TelegramConnector:
    """A chat channel that long-polls Telegram updates and delivers replies."""

    transport_id = TELEGRAM_TRANSPORT_ID

    def __init__(
        self,
        *,
        token: str,
        api_base: str = "https://api.telegram.org",
        allowed_chat_ids: Collection[int] = (),
        poll_timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
        stderr: TextIO | None = None,
    ) -> None:
        self._token = token
        self._api_base = api_base
        self._allowed_chat_ids = tuple(allowed_chat_ids)
        self._poll_timeout = poll_timeout_seconds
        self._client = (
            client
            if client is not None
            else httpx.AsyncClient(timeout=_SEND_TIMEOUT_SECONDS)
        )
        self._owns_client = client is None
        self._stderr = sys.stderr if stderr is None else stderr
        self._offset: int | None = None

    async def run(self, submit: InboundHandler) -> None:
        """Confirm the startup backlog, then poll updates until cancelled.

        Updates that arrived while the host was down are confirmed without
        running a turn, so a restart never replays old chat into the agent. A
        deliberate transport failure is reported and retried, never fatal.
        """
        try:
            await self._drain()
        except TransportError as exc:
            self._warn(f"warning: telegram channel could not read its backlog: {exc}")
        while True:
            try:
                updates = await self._get_updates(self._poll_timeout)
            except TransportError as exc:
                self._warn(f"warning: telegram channel poll failed: {exc}")
                await asyncio.sleep(_ERROR_RETRY_SECONDS)
                continue
            for update in updates:
                self._offset = update.update_id + 1
                envelope = update.envelope
                if envelope is None:
                    continue
                try:
                    await submit(envelope)
                except NewbotError as exc:
                    self._warn(f"warning: telegram turn failed: {exc}")

    async def deliver(self, envelope: OutboundEnvelope) -> None:
        """Send one reply to its chat."""
        result = await self._call(
            "sendMessage",
            {"chat_id": _chat_id(envelope.conversation_id), "text": envelope.text},
            timeout=_SEND_TIMEOUT_SECONDS,
        )
        try:
            _MessageId.model_validate(result)
        except ValidationError as exc:
            raise TransportError(
                f"telegram sendMessage response was invalid: {exc}"
            ) from exc

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _drain(self) -> None:
        """Confirm the pending backlog so it is never replayed."""
        updates = await self._get_updates(0.0)
        if updates:
            self._offset = updates[-1].update_id + 1

    async def _get_updates(self, timeout: float) -> tuple[TelegramUpdate, ...]:
        payload: dict[str, object] = {"timeout": timeout}
        if self._offset is not None:
            payload["offset"] = self._offset
        result = await self._call(
            "getUpdates", payload, timeout=timeout + _REQUEST_SLACK_SECONDS
        )
        if not isinstance(result, list):
            raise TransportError("telegram getUpdates result must be a list")
        updates: list[TelegramUpdate] = []
        for item in result:
            if not isinstance(item, dict):
                raise TransportError("telegram update must be an object")
            updates.append(
                parse_update(item, allowed_chat_ids=self._allowed_chat_ids)
            )
        return tuple(updates)

    async def _call(
        self, method: str, payload: Mapping[str, object], *, timeout: float
    ) -> object:
        url = f"{self._api_base.rstrip('/')}/bot{self._token}/{method}"
        try:
            response = await self._client.post(url, json=payload, timeout=timeout)
        except httpx.HTTPError as exc:
            raise TransportError(
                f"telegram {method} request failed: {_redact(str(exc), self._token)}"
            ) from exc
        try:
            body: object = response.json()
        except ValueError as exc:
            raise TransportError(f"telegram {method} returned invalid JSON") from exc
        if response.status_code != httpx.codes.OK:
            raise TransportError(
                f"telegram {method} returned HTTP {response.status_code}: "
                f"{_description(body)}"
            )
        if not isinstance(body, dict) or body.get("ok") is not True:
            raise TransportError(f"telegram {method} failed: {_description(body)}")
        return body.get("result")

    def _warn(self, message: str) -> None:
        self._stderr.write(f"{message}\n")
        self._stderr.flush()


def _chat_id(conversation: str) -> int:
    if _CHAT_ID.fullmatch(conversation) is None:
        raise TransportError(f"telegram conversation {conversation!r} is not a chat id")
    return int(conversation)


def _description(body: object) -> str:
    if isinstance(body, Mapping):
        description = body.get("description")
        if isinstance(description, str) and description:
            return description[:_MAX_ERROR_CHARS]
    return "no description"


def _redact(text: str, secret: str) -> str:
    """Keep the bot token out of warnings; the request URL embeds it."""
    if not secret:
        return text
    return text.replace(secret, "***")
