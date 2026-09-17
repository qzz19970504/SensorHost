"""OTAF frame codec and device-reply parsing for the STM32 UART OTA link.

The wire contract mirrors the firmware's ``app/Control/ota_protocol_core`` and
``Common/Ota/ota_reply_core.c`` exactly; this module is self-contained and does
not import anything from the firmware repository.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from enum import IntEnum


FRAME_MAGIC = b"OTAF"
FRAME_VERSION = 1
FRAME_HEADER_SIZE = 20
FRAME_MAX_PAYLOAD = 512
FRAME_CRC_SIZE = 4
FRAME_MAX_SIZE = FRAME_HEADER_SIZE + FRAME_MAX_PAYLOAD + FRAME_CRC_SIZE
BEGIN_PAYLOAD_SIZE = 80

_HEADER = struct.Struct("<4sBBHIIHH")


class OtaCodecError(ValueError):
    """Report an invalid OTAF frame or device reply."""


class FrameType(IntEnum):
    """Enumerate the four upstream OTAF frame kinds."""

    BEGIN = 1
    DATA = 2
    COMMIT = 3
    CANCEL = 4


@dataclass(frozen=True)
class UploadFrame:
    """Describe one upstream OTAF frame before encoding."""

    frame_type: FrameType
    sequence: int
    offset: int
    payload: bytes


@dataclass(frozen=True)
class DeviceResponse:
    """Describe one decoded ``+OTA:`` device reply line."""

    acknowledged: bool
    sequence: int
    next_offset: int
    code: str | None = None
    version: str | None = None
    crc: int | None = None

    @property
    def staged(self) -> bool:
        """Return whether this reply is the terminal ``+OTA:STAGED`` event."""
        return self.code == "STAGED"


def encode_frame(frame: UploadFrame) -> bytes:
    """Serialize one OTAF frame with its trailing CRC32 over header+payload."""
    payload = bytes(frame.payload)
    if len(payload) > FRAME_MAX_PAYLOAD:
        raise OtaCodecError("frame payload exceeds 512 bytes")
    if frame.frame_type is FrameType.BEGIN and (
        frame.sequence != 0
        or frame.offset != 0
        or len(payload) != BEGIN_PAYLOAD_SIZE
    ):
        raise OtaCodecError("BEGIN frame fields are invalid")
    if frame.frame_type in (FrameType.COMMIT, FrameType.CANCEL) and payload:
        raise OtaCodecError("control frame must not contain payload")
    if not 0 <= frame.sequence <= 0xFFFFFFFF:
        raise OtaCodecError("sequence must fit in 32 bits")
    if not 0 <= frame.offset <= 0xFFFFFFFF:
        raise OtaCodecError("offset must fit in 32 bits")
    header = _HEADER.pack(
        FRAME_MAGIC,
        FRAME_VERSION,
        int(frame.frame_type),
        FRAME_HEADER_SIZE,
        frame.sequence,
        frame.offset,
        len(payload),
        0,
    )
    body = header + payload
    return body + struct.pack("<I", zlib.crc32(body) & 0xFFFFFFFF)


def decode_frame(data: bytes) -> UploadFrame:
    """Validate and decode one complete OTAF frame including its CRC32."""
    if len(data) < FRAME_HEADER_SIZE + FRAME_CRC_SIZE:
        raise OtaCodecError("frame is truncated")
    magic, version, frame_type, header_size, sequence, offset, length, reserved = (
        _HEADER.unpack_from(data, 0)
    )
    if magic != FRAME_MAGIC or version != FRAME_VERSION:
        raise OtaCodecError("frame header is invalid")
    if header_size != FRAME_HEADER_SIZE or reserved != 0 or length > FRAME_MAX_PAYLOAD:
        raise OtaCodecError("frame header fields are invalid")
    if len(data) != FRAME_HEADER_SIZE + length + FRAME_CRC_SIZE:
        raise OtaCodecError("frame length is invalid")
    expected = struct.unpack_from("<I", data, FRAME_HEADER_SIZE + length)[0]
    actual = zlib.crc32(data[: FRAME_HEADER_SIZE + length]) & 0xFFFFFFFF
    if expected != actual:
        raise OtaCodecError("frame CRC is invalid")
    try:
        decoded_type = FrameType(frame_type)
    except ValueError as error:
        raise OtaCodecError("frame type is invalid") from error
    return UploadFrame(
        frame_type=decoded_type,
        sequence=sequence,
        offset=offset,
        payload=data[FRAME_HEADER_SIZE : FRAME_HEADER_SIZE + length],
    )


def parse_response(line: bytes) -> DeviceResponse:
    """Decode one bare ``+OTA:`` reply line into a structured response."""
    text = bytes(line).decode("ascii", errors="strict").strip()
    if text.startswith("+OTA:ACK,"):
        fields = _parse_fields(text[len("+OTA:ACK,") :])
        if "SEQ" not in fields or "NEXT" not in fields:
            raise OtaCodecError("ACK fields are missing")
        return DeviceResponse(True, int(fields["SEQ"], 0), int(fields["NEXT"], 0))
    if text.startswith("+OTA:NACK,"):
        fields = _parse_fields(text[len("+OTA:NACK,") :])
        if any(name not in fields for name in ("CODE", "SEQ", "NEXT")):
            raise OtaCodecError("NACK fields are missing")
        return DeviceResponse(
            False, int(fields["SEQ"], 0), int(fields["NEXT"], 0), fields["CODE"]
        )
    if text.startswith("+OTA:STAGED,"):
        fields = _parse_fields(text[len("+OTA:STAGED,") :])
        if "VERSION" not in fields or "CRC" not in fields:
            raise OtaCodecError("STAGED fields are missing")
        return DeviceResponse(
            True,
            0,
            0,
            "STAGED",
            version=fields["VERSION"],
            crc=int(fields["CRC"], 16),
        )
    raise OtaCodecError(f"unexpected device response: {text!r}")


def parse_ready(line: bytes) -> tuple[int, int]:
    """Extract ``(max_image, chunk)`` from one ``+OTA:READY`` handshake line."""
    text = bytes(line).decode("ascii", errors="strict").strip()
    if not text.startswith("+OTA:READY,"):
        raise OtaCodecError(f"unexpected handshake reply: {text!r}")
    fields = _parse_fields(text[len("+OTA:READY,") :])
    if "MAX" not in fields or "CHUNK" not in fields:
        raise OtaCodecError("READY fields are missing")
    return int(fields["MAX"], 0), int(fields["CHUNK"], 0)


def _parse_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for item in text.split(","):
        if not item:
            continue
        if "=" not in item:
            raise OtaCodecError("response field is malformed")
        name, value = item.split("=", 1)
        fields[name] = value
    return fields
