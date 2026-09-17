"""Line/frame demultiplexer that splits one mixed OTA stream in two.

During an OTA session the same physical stream (an ESP32 TCP bridge or a bench
UART) can carry three kinds of bytes at once:

* upstream OTAF binary frames (host -> device, never seen here),
* downstream bare ``+OTA:`` text lines and standalone ``OK`` lines, and
* occasional downstream SDF1 binary frames (STATUS / CLI responses).

The demultiplexer is SDF1-frame aware.  At each scan position it first checks
for the ``SDF1`` magic: a whole frame is extracted by its header length and
handed to the parser untouched, so binary payload bytes (which may legitimately
contain ``OK\\r\\n`` inside a CLI_RESPONSE frame) are never mistaken for a text
line.  Only when the position is not an SDF1 frame does it split on ``\\n`` and
claim lines whose stripped form starts with ``+OTA:`` or equals ``OK``.  Every
other byte is returned, in order, so the caller can keep feeding the existing
:class:`~sensor_host.protocol.sdf1.StreamParser`.

Incomplete trailing data (a partial SDF1 frame or a partial text line) is held
until the next read; bounded safeguards flush a held residue that can never
complete so a stream is never starved.
"""

from __future__ import annotations

from sensor_host.protocol.sdf1 import (
    CRC_SIZE,
    HEADER_SIZE,
    MAGIC,
    MAX_HEADER_SIZE,
    MAX_PAYLOAD_SIZE,
)

_OTA_PREFIX = b"+OTA:"
_OK_LINE = b"OK"
_NEWLINE = 0x0A
_DEFAULT_MAX_LINE = 128
# An SDF1 frame is at most MAX_HEADER_SIZE + MAX_PAYLOAD_SIZE + CRC_SIZE bytes;
# a held partial frame beyond this bound can never be valid, so flush it.
_MAX_FRAME_HOLD = MAX_HEADER_SIZE + MAX_PAYLOAD_SIZE + CRC_SIZE + 64
# Header fields header_size/payload_size live at offsets 8..12.
_HEADER_LENGTH_BYTES = 12


class StreamDemultiplexer:
    """Split a mixed OTA/SDF1 byte stream into OTA lines and parser bytes."""

    def __init__(self, max_line: int = _DEFAULT_MAX_LINE) -> None:
        if max_line <= 0:
            raise ValueError("max_line must be positive")
        self._pending = bytearray()
        self._max_line = max_line

    @property
    def buffered_bytes(self) -> int:
        """Return the number of residue bytes held for the next feed."""
        return len(self._pending)

    def reset(self) -> None:
        """Discard any held residue, e.g. when a new OTA session starts."""
        self._pending.clear()

    def feed(self, chunk: bytes | bytearray | memoryview) -> tuple[list[bytes], bytes]:
        """Consume one read chunk; return ``(ota_lines, parser_bytes)``."""
        self._pending.extend(chunk)
        ota_lines: list[bytes] = []
        parser_parts: list[bytes] = []
        while self._pending:
            if self._starts_sdf1_frame():
                frame_length = self._sdf1_frame_length()
                if frame_length is None:
                    break  # incomplete frame: hold and wait for more bytes
                if frame_length == 0:
                    # Magic matched but the header is invalid; advance one byte
                    # so the parser can resync exactly like StreamParser does.
                    parser_parts.append(bytes(self._pending[:1]))
                    del self._pending[:1]
                    continue
                parser_parts.append(bytes(self._pending[:frame_length]))
                del self._pending[:frame_length]
                continue
            newline = self._pending.find(_NEWLINE)
            if newline < 0:
                break  # incomplete text line: hold and wait for its terminator
            line = bytes(self._pending[:newline])
            del self._pending[: newline + 1]
            stripped = line.strip()
            if stripped.startswith(_OTA_PREFIX) or stripped == _OK_LINE:
                ota_lines.append(stripped)
            else:
                # Re-append the removed newline so the parser sees identical
                # bytes for any non-OTA text it must discard.
                parser_parts.append(line + b"\n")
        residue = self._release_held_residue()
        if residue:
            parser_parts.append(residue)
        return ota_lines, b"".join(parser_parts)

    def flush(self) -> bytes:
        """Release every held byte to the parser, e.g. when a session ends."""
        residue = bytes(self._pending)
        self._pending.clear()
        return residue

    def _starts_sdf1_frame(self) -> bool:
        """Return whether the held residue begins with a full SDF1 magic."""
        return len(self._pending) >= len(MAGIC) and self._pending[: len(MAGIC)] == MAGIC

    def _sdf1_frame_length(self) -> int | None:
        """Return one frame's byte length, 0 if invalid, None if incomplete."""
        buffer = self._pending
        if len(buffer) < _HEADER_LENGTH_BYTES:
            return None
        header_size = int.from_bytes(buffer[8:10], "little")
        payload_size = int.from_bytes(buffer[10:12], "little")
        if not HEADER_SIZE <= header_size <= MAX_HEADER_SIZE:
            return 0
        if payload_size > MAX_PAYLOAD_SIZE:
            return 0
        frame_size = header_size + payload_size + CRC_SIZE
        if len(buffer) < frame_size:
            return None
        return frame_size

    def _release_held_residue(self) -> bytes:
        """Flush a held residue that can never complete; otherwise keep it."""
        if not self._pending:
            return b""
        if self._is_frame_prefix():
            if len(self._pending) > _MAX_FRAME_HOLD:
                return self._take_all()
            return b""
        if len(self._pending) > self._max_line:
            return self._take_all()
        return b""

    def _is_frame_prefix(self) -> bool:
        """Return whether the residue could still grow into an SDF1 frame."""
        if self._starts_sdf1_frame():
            return True
        return len(self._pending) < len(MAGIC) and MAGIC.startswith(
            bytes(self._pending)
        )

    def _take_all(self) -> bytes:
        released = bytes(self._pending)
        self._pending.clear()
        return released
