"""Contract tests for the workbench's RFC 6455 framing."""

from __future__ import annotations

import io
import struct

import pytest

from newbot.adapters.transports.websocket import (
    CLOSE_MESSAGE_TOO_BIG,
    CLOSE_NORMAL,
    CLOSE_PROTOCOL_ERROR,
    MAX_MESSAGE_BYTES,
    WebSocketConnection,
    WebSocketError,
    accept_key,
)

_MASK = b"\x01\x02\x03\x04"


def _frame(
    opcode: int, payload: bytes, *, fin: bool = True, masked: bool = True
) -> bytes:
    opcode_byte = (0x80 if fin else 0x00) | opcode
    mask_bit = 0x80 if masked else 0x00
    length = len(payload)
    if length < 126:
        header = bytes([opcode_byte, mask_bit | length])
    elif length < 1 << 16:
        header = bytes([opcode_byte, mask_bit | 126]) + struct.pack("!H", length)
    else:
        header = bytes([opcode_byte, mask_bit | 127]) + struct.pack("!Q", length)
    if not masked:
        return header + payload
    masked_payload = bytes(
        byte ^ _MASK[index % 4] for index, byte in enumerate(payload)
    )
    return header + _MASK + masked_payload


def test_accept_key_matches_the_rfc_6455_example() -> None:
    assert accept_key("dGhlIHNhbXBsZSBub25jZQ==") == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="


def test_receive_text_answers_ping_and_assembles_fragments() -> None:
    stream = io.BytesIO(
        _frame(0x9, b"hi") + _frame(0x1, b"hel", fin=False) + _frame(0x0, b"lo")
    )
    writer = io.BytesIO()

    assert WebSocketConnection(stream, writer).receive_text() == "hello"
    assert writer.getvalue() == _frame(0xA, b"hi", masked=False)


def test_receive_text_returns_none_when_the_peer_closes() -> None:
    payload = struct.pack("!H", CLOSE_NORMAL)
    writer = io.BytesIO()

    connection = WebSocketConnection(io.BytesIO(_frame(0x8, payload)), writer)

    assert connection.receive_text() is None
    assert writer.getvalue() == _frame(0x8, payload, masked=False)


def test_receive_text_rejects_an_unmasked_frame() -> None:
    connection = WebSocketConnection(
        io.BytesIO(_frame(0x1, b"hi", masked=False)), io.BytesIO()
    )

    with pytest.raises(WebSocketError) as info:
        connection.receive_text()

    assert info.value.code == CLOSE_PROTOCOL_ERROR


def test_receive_text_rejects_an_oversized_message() -> None:
    oversized = _frame(0x1, b"a" * (MAX_MESSAGE_BYTES + 1))
    connection = WebSocketConnection(io.BytesIO(oversized), io.BytesIO())

    with pytest.raises(WebSocketError) as info:
        connection.receive_text()

    assert info.value.code == CLOSE_MESSAGE_TOO_BIG


def test_send_text_writes_an_unmasked_text_frame() -> None:
    writer = io.BytesIO()

    WebSocketConnection(io.BytesIO(), writer).send_text("hi")

    assert writer.getvalue() == _frame(0x1, b"hi", masked=False)
