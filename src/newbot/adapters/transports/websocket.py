"""Server-side RFC 6455 framing for the loopback workbench.

Only what the workbench needs is implemented: text messages over one
connection, with no extensions, subprotocols, or compression. Inbound frames
must be masked (RFC 6455 section 5.1), control frames are answered, and every
message is bounded, so a malformed or hostile peer is rejected at the wire
boundary instead of reaching agent code.
"""

from __future__ import annotations

import base64
import hashlib
import io
import struct

_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

_CONTINUATION = 0x0
_TEXT = 0x1
_CLOSE = 0x8
_PING = 0x9
_PONG = 0xA

MAX_MESSAGE_BYTES = 1 << 20
"""Largest assembled message the workbench accepts from a peer."""

CLOSE_NORMAL = 1000
CLOSE_PROTOCOL_ERROR = 1002
CLOSE_UNSUPPORTED_DATA = 1003
CLOSE_MESSAGE_TOO_BIG = 1009


class WebSocketError(Exception):
    """A peer broke the framing contract; ``code`` is the status to send back."""

    def __init__(self, code: int, reason: str) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason


def accept_key(client_key: str) -> str:
    """Return the ``Sec-WebSocket-Accept`` value for a client's key."""
    digest = hashlib.sha1((client_key + _GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


class WebSocketConnection:
    """Reads and writes RFC 6455 text messages over one upgraded socket."""

    def __init__(self, reader: io.BufferedIOBase, writer: io.BufferedIOBase) -> None:
        self._reader = reader
        self._writer = writer

    def receive_text(self) -> str | None:
        """Return the next text message, or ``None`` once the peer closes."""
        fragments: list[bytes] = []
        started = False
        size = 0
        while True:
            fin, opcode, payload = self._read_frame()
            if opcode == _PING:
                self._send_frame(_PONG, payload)
                continue
            if opcode == _PONG:
                continue
            if opcode == _CLOSE:
                self._send_frame(_CLOSE, payload[:2])
                return None
            if opcode == _CONTINUATION:
                if not started:
                    raise WebSocketError(CLOSE_PROTOCOL_ERROR, "orphan continuation")
            elif opcode == _TEXT:
                if started:
                    raise WebSocketError(CLOSE_PROTOCOL_ERROR, "message interrupted")
                started = True
            else:
                raise WebSocketError(CLOSE_UNSUPPORTED_DATA, "non-text message")
            size += len(payload)
            if size > MAX_MESSAGE_BYTES:
                raise WebSocketError(CLOSE_MESSAGE_TOO_BIG, "message too large")
            fragments.append(payload)
            if fin:
                break
        try:
            return b"".join(fragments).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WebSocketError(CLOSE_UNSUPPORTED_DATA, "invalid utf-8") from exc

    def send_text(self, text: str) -> None:
        """Send one unmasked text message."""
        self._send_frame(_TEXT, text.encode("utf-8"))

    def close(self, code: int = CLOSE_NORMAL, reason: str = "") -> None:
        """Send a close frame; the peer's acknowledgement is not awaited."""
        self._send_frame(_CLOSE, struct.pack("!H", code) + reason.encode("utf-8"))

    def _read_frame(self) -> tuple[bool, int, bytes]:
        header = self._read_exact(2)
        if header[0] & 0x70:
            raise WebSocketError(CLOSE_PROTOCOL_ERROR, "reserved bits set")
        fin = bool(header[0] & 0x80)
        opcode = header[0] & 0x0F
        masked = bool(header[1] & 0x80)
        length = header[1] & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._read_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._read_exact(8))[0]
        if opcode >= _CLOSE and (not fin or length > 125):
            raise WebSocketError(CLOSE_PROTOCOL_ERROR, "invalid control frame")
        if not masked:
            raise WebSocketError(CLOSE_PROTOCOL_ERROR, "client frame is not masked")
        if length > MAX_MESSAGE_BYTES:
            raise WebSocketError(CLOSE_MESSAGE_TOO_BIG, "frame too large")
        mask = self._read_exact(4)
        payload = bytearray(self._read_exact(length))
        for index in range(length):
            payload[index] ^= mask[index % 4]
        return fin, opcode, bytes(payload)

    def _read_exact(self, size: int) -> bytes:
        data = self._reader.read(size)
        if len(data) != size:
            raise WebSocketError(CLOSE_PROTOCOL_ERROR, "connection closed mid-frame")
        return data

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        length = len(payload)
        if length < 126:
            header = struct.pack("!BB", 0x80 | opcode, length)
        elif length < 1 << 16:
            header = struct.pack("!BBH", 0x80 | opcode, 126, length)
        else:
            header = struct.pack("!BBQ", 0x80 | opcode, 127, length)
        self._writer.write(header + payload)
        self._writer.flush()
