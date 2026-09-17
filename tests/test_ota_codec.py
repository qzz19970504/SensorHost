"""Unit tests for the OTAF frame codec and device-reply parsing."""

from __future__ import annotations

import struct
import zlib

import pytest

from sensor_host.ota.codec import (
    FRAME_HEADER_SIZE,
    FRAME_MAX_PAYLOAD,
    DeviceResponse,
    FrameType,
    OtaCodecError,
    UploadFrame,
    decode_frame,
    encode_frame,
    parse_ready,
    parse_response,
)


def test_encode_decode_data_frame_roundtrip() -> None:
    payload = bytes(range(64))
    frame = UploadFrame(FrameType.DATA, sequence=7, offset=512, payload=payload)

    encoded = encode_frame(frame)
    decoded = decode_frame(encoded)

    assert decoded == frame
    assert len(encoded) == FRAME_HEADER_SIZE + len(payload) + 4
    expected_crc = zlib.crc32(encoded[:-4]) & 0xFFFFFFFF
    assert struct.unpack_from("<I", encoded, len(encoded) - 4)[0] == expected_crc


def test_encode_begin_frame_requires_manifest_prefix() -> None:
    with pytest.raises(OtaCodecError):
        encode_frame(UploadFrame(FrameType.BEGIN, 0, 0, b"\x00" * 79))
    with pytest.raises(OtaCodecError):
        encode_frame(UploadFrame(FrameType.BEGIN, 1, 0, b"\x00" * 80))
    encode_frame(UploadFrame(FrameType.BEGIN, 0, 0, b"\x00" * 80))


def test_encode_control_frames_reject_payload() -> None:
    with pytest.raises(OtaCodecError):
        encode_frame(UploadFrame(FrameType.COMMIT, 3, 1024, b"\x01"))
    with pytest.raises(OtaCodecError):
        encode_frame(UploadFrame(FrameType.CANCEL, 3, 1024, b"\x01"))
    encode_frame(UploadFrame(FrameType.COMMIT, 3, 1024, b""))
    encode_frame(UploadFrame(FrameType.CANCEL, 3, 1024, b""))


def test_encode_rejects_oversized_payload() -> None:
    with pytest.raises(OtaCodecError):
        encode_frame(
            UploadFrame(FrameType.DATA, 1, 0, b"\x00" * (FRAME_MAX_PAYLOAD + 1))
        )


def test_decode_rejects_truncated_frame() -> None:
    encoded = encode_frame(UploadFrame(FrameType.DATA, 1, 0, b"abc"))
    with pytest.raises(OtaCodecError):
        decode_frame(encoded[:-1])
    with pytest.raises(OtaCodecError):
        decode_frame(encoded[:FRAME_HEADER_SIZE])


def test_decode_rejects_bad_crc() -> None:
    encoded = bytearray(encode_frame(UploadFrame(FrameType.DATA, 1, 0, b"abc")))
    encoded[-1] ^= 0xFF
    with pytest.raises(OtaCodecError):
        decode_frame(bytes(encoded))


def test_decode_rejects_nonzero_reserved_field() -> None:
    encoded = bytearray(encode_frame(UploadFrame(FrameType.DATA, 1, 0, b"abc")))
    # reserved lives at header offset 18..19; poison it and fix the CRC so the
    # reserved-field check (not the CRC check) is what rejects the frame.
    encoded[18] = 0x01
    body = bytes(encoded[: FRAME_HEADER_SIZE + 3])
    encoded[-4:] = struct.pack("<I", zlib.crc32(body) & 0xFFFFFFFF)
    with pytest.raises(OtaCodecError):
        decode_frame(bytes(encoded))


def test_decode_rejects_bad_magic_and_version() -> None:
    encoded = bytearray(encode_frame(UploadFrame(FrameType.DATA, 1, 0, b"abc")))
    encoded[0] = ord("X")
    with pytest.raises(OtaCodecError):
        decode_frame(bytes(encoded))

    encoded = bytearray(encode_frame(UploadFrame(FrameType.DATA, 1, 0, b"abc")))
    encoded[4] = 2  # version
    with pytest.raises(OtaCodecError):
        decode_frame(bytes(encoded))


def test_parse_response_ack() -> None:
    response = parse_response(b"+OTA:ACK,SEQ=4,NEXT=2048\r\n")
    assert response == DeviceResponse(True, 4, 2048, None)
    assert response.staged is False


def test_parse_response_nack() -> None:
    response = parse_response(b"+OTA:NACK,CODE=IMAGE_CRC,SEQ=9,NEXT=512")
    assert response.acknowledged is False
    assert response.code == "IMAGE_CRC"
    assert response.sequence == 9
    assert response.next_offset == 512


def test_parse_response_staged_extracts_version_and_crc() -> None:
    response = parse_response(b"+OTA:STAGED,VERSION=1.2.3,CRC=0A1B2C3D\r\n")
    assert response.staged is True
    assert response.version == "1.2.3"
    assert response.crc == 0x0A1B2C3D


def test_parse_response_rejects_unexpected_line() -> None:
    with pytest.raises(OtaCodecError):
        parse_response(b"+STATE:IDLE")
    with pytest.raises(OtaCodecError):
        parse_response(b"+OTA:ACK,SEQ=1")


def test_parse_ready_extracts_max_and_chunk() -> None:
    max_image, chunk = parse_ready(b"+OTA:READY,PROTO=1,MAX=327680,CHUNK=512\r\n")
    assert max_image == 327680
    assert chunk == 512
    with pytest.raises(OtaCodecError):
        parse_ready(b"+OTA:ACK,SEQ=1,NEXT=0")
