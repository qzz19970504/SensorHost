from __future__ import annotations

import json
import random
import struct
import sys
import zlib
import uuid
from pathlib import Path

import pytest

HOST_SOURCE = Path(__file__).resolve().parents[1] / "host" / "src"
sys.path.insert(0, str(HOST_SOURCE))

from protocol import (
    HEADER_SIZE,
    DATA_HEADER_SIZE,
    MAX_PAYLOAD_SIZE,
    MessageType,
    StreamParser,
)


ROOT = Path(__file__).resolve().parent


def encode_frame(
    message_type: int,
    sequence: int,
    payload: bytes,
    *,
    flags: int = 0,
    timestamp_us: int = 123,
    item_count: int = 1,
    version: int = 1,
    header_size: int = HEADER_SIZE,
    payload_size: int | None = None,
    device_uuid: uuid.UUID | None = None,
) -> bytes:
    declared_size = len(payload) if payload_size is None else payload_size
    header = struct.pack(
        "<4sBBHHHIQHH",
        b"SDF1",
        version,
        message_type,
        flags,
        header_size,
        declared_size,
        sequence,
        timestamp_us,
        item_count,
        0,
    )
    extension = device_uuid.bytes if device_uuid is not None else b""
    body = header + extension + payload
    return body + struct.pack("<I", zlib.crc32(body) & 0xFFFFFFFF)


@pytest.fixture(scope="module")
def golden() -> tuple[bytes, list[dict[str, object]]]:
    data = (ROOT / "golden" / "stream_v1_frames.bin").read_bytes()
    manifest = json.loads(
        (ROOT / "golden" / "stream_v1_frames.json").read_text(encoding="utf-8")
    )
    return data, manifest["frames"]


@pytest.mark.parametrize("chunk_size", [1, 2, 7, 31, 4096])
def test_parses_golden_with_fixed_chunks(golden, chunk_size: int) -> None:
    data, manifest = golden
    parser = StreamParser()
    frames = []
    for offset in range(0, len(data), chunk_size):
        frames.extend(parser.feed(data[offset : offset + chunk_size]))

    assert [frame.message_type for frame in frames] == [
        MessageType(case["message_type"]) for case in manifest
    ]
    assert [frame.sequence for frame in frames] == [1, 2, 3, 4]
    assert parser.stats.frames == 4
    assert parser.stats.sequence_gaps == 0
    assert frames[0].device_uuid == uuid.UUID("00112233-4455-6677-8899-aabbccddeeff")
    assert frames[1].device_uuid == frames[0].device_uuid
    assert frames[2].device_uuid is None


def test_random_chunks_and_concatenated_frames(golden) -> None:
    data, _ = golden
    parser = StreamParser()
    randomizer = random.Random(20260827)
    frames = []
    offset = 0
    while offset < len(data):
        size = randomizer.randint(1, 19)
        frames.extend(parser.feed(data[offset : offset + size]))
        offset += size
    assert len(frames) == 4
    assert frames[-1].cli_text == "transport=cdc\r\n"


def test_recovers_from_garbage_and_bad_crc(golden) -> None:
    data, manifest = golden
    first_length = int(manifest[0]["length"])
    second_length = int(manifest[1]["length"])
    damaged = bytearray(data[:first_length])
    damaged[-1] ^= 0xFF
    second = data[first_length : first_length + second_length]
    parser = StreamParser()

    frames = parser.feed(b"garbage-prefix" + bytes(damaged) + second)

    assert [frame.message_type for frame in frames] == [MessageType.JY61PL_SAMPLE]
    assert parser.stats.crc_errors == 1
    assert parser.stats.bytes_discarded >= len(b"garbage-prefix")


def test_rejects_bad_header_oversize_and_unknown_type(golden) -> None:
    data, manifest = golden
    first = data[: int(manifest[0]["length"])]
    bad_header = encode_frame(MessageType.CLI_RESPONSE, 5, b"x", header_size=27)
    oversized = encode_frame(
        MessageType.CLI_RESPONSE,
        6,
        b"",
        payload_size=MAX_PAYLOAD_SIZE + 1,
    )
    unknown = encode_frame(0x7F, 7, b"future")
    parser = StreamParser()

    frames = parser.feed(bad_header + oversized + unknown + first)

    assert [frame.message_type for frame in frames] == [MessageType.IIS3DWB_FIFO]
    assert parser.stats.header_errors == 1
    assert parser.stats.length_errors == 1
    assert parser.stats.unknown_types == 1


def test_control_frames_do_not_advance_sensor_sequence() -> None:
    parser = StreamParser()
    stream = (
        encode_frame(MessageType.IIS3DWB_FIFO, 10, bytes(7))
        + encode_frame(MessageType.CLI_RESPONSE, 0, b"OK\r\n")
        + encode_frame(MessageType.STATUS, 0, bytes(64))
        + encode_frame(MessageType.JY61PL_SAMPLE, 11, bytes(14))
    )
    assert len(parser.feed(stream)) == 4
    assert parser.stats.sequence_gaps == 0
    assert parser.last_sequence == 11


def test_counts_sensor_sequence_gap() -> None:
    parser = StreamParser()
    stream = (
        encode_frame(MessageType.IIS3DWB_FIFO, 10, bytes(7))
        + encode_frame(MessageType.JY61PL_SAMPLE, 13, bytes(14))
    )
    assert len(parser.feed(stream)) == 2
    assert parser.stats.sequence_gaps == 2


def test_skips_crc_valid_future_version_as_one_bounded_frame() -> None:
    parser = StreamParser()
    future_payload = b"prefix-SDF1-inside-payload-suffix"
    future = encode_frame(
        MessageType.CLI_RESPONSE,
        20,
        future_payload,
        version=3,
    )
    current = encode_frame(MessageType.CLI_RESPONSE, 21, b"current")

    frames = parser.feed(future + current)

    assert [frame.cli_text for frame in frames] == ["current"]
    assert parser.stats.unknown_versions == 1
    assert parser.stats.bytes_discarded == 0
    assert parser.stats.sequence_gaps == 0


def test_future_version_still_requires_valid_crc() -> None:
    future = bytearray(
        encode_frame(MessageType.CLI_RESPONSE, 30, b"SDF1", version=3)
    )
    future[-1] ^= 0x80
    parser = StreamParser()

    parser.feed(future)

    assert parser.stats.unknown_versions == 0
    assert parser.stats.crc_errors == 1


def test_decodes_v2_sensor_uuid_and_archive_flag_without_stripping_payload() -> None:
    expected_uuid = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
    payload = bytes(range(14))
    frame = encode_frame(
        MessageType.IIS3DWB_FIFO,
        77,
        payload,
        flags=0x8002,
        item_count=2,
        version=2,
        header_size=DATA_HEADER_SIZE,
        device_uuid=expected_uuid,
    )

    decoded = StreamParser().feed(frame)[0]

    assert decoded.device_uuid == expected_uuid
    assert decoded.archive_export
    assert decoded.payload == payload


@pytest.mark.parametrize("message_type", [MessageType.STATUS, MessageType.CLI_RESPONSE])
def test_rejects_v2_control_frames(message_type: MessageType) -> None:
    frame = encode_frame(
        message_type,
        1,
        bytes(64) if message_type is MessageType.STATUS else b"OK\r\n",
        version=2,
        header_size=DATA_HEADER_SIZE,
        device_uuid=uuid.UUID(int=0),
    )
    parser = StreamParser()

    assert parser.feed(frame) == []
    assert parser.stats.header_errors == 1


def test_decodes_jy61pl_scaling_and_status() -> None:
    jy_payload = struct.pack("<7h", 16384, -16384, 0, 2534, 16384, -16384, 0)
    status_payload = bytearray(64)
    struct.pack_into("<BBBBHH9I5H2xQ", status_payload, 0,
                     1, 1, 2, 1, 256, 3,
                     0, 3, 4, 5, 6, 7, 8, 9, 10,
                     111, 222, 333, 444, 555, 987654321)
    parser = StreamParser()
    frames = parser.feed(
        encode_frame(MessageType.JY61PL_SAMPLE, 1, jy_payload)
        + encode_frame(MessageType.STATUS, 2, bytes(status_payload))
    )

    jy = frames[0].jy61pl
    assert jy is not None
    assert jy.raw == (16384, -16384, 0, 2534, 16384, -16384, 0)
    assert jy.acceleration_g == pytest.approx((8.0, -8.0, 0.0))
    assert jy.temperature_c == pytest.approx(25.34)
    assert jy.angles_deg == pytest.approx((90.0, -90.0, 0.0))
    status = frames[1].status
    assert status is not None
    assert status.watermark_words == 256
    assert status.uart_credit_bytes == 0
    assert status.iis_stack_high_water_words == 111
    assert status.uptime_us == 987654321


def test_decodes_iis_tags_on_mcu_monotonic_timeline() -> None:
    timestamp_word = bytes([4 << 3]) + struct.pack("<I", 1000) + b"\x00\x00"
    accel_word = bytes([2 << 3]) + struct.pack("<hhh", 100, -200, 300)
    parser = StreamParser()
    frame = parser.feed(
        encode_frame(
            MessageType.IIS3DWB_FIFO,
            1,
            timestamp_word + accel_word,
            flags=0x0002,
            timestamp_us=999999,
            item_count=2,
        )
    )[0]

    assert frame.iis_words is not None
    assert frame.iis_words[0].sensor_tag == 4
    assert frame.iis_words[0].timestamp_ticks == 1000
    assert frame.iis_words[1].sensor_tag == 2
    assert frame.iis_words[1].acceleration_raw == (100, -200, 300)
    assert frame.iis_samples is not None
    assert frame.iis_samples[0].timestamp_us == pytest.approx(999999.0)
    assert frame.iis_samples[0].acceleration_raw == (100, -200, 300)


def test_iis_timestamp_offset_persists_without_a_tag() -> None:
    timestamp_word = bytes([4 << 3]) + struct.pack("<I", 1000) + b"\x00\x00"
    accel_word = bytes([2 << 3]) + struct.pack("<hhh", 1, 2, 3)
    parser = StreamParser()

    first = parser.feed(
        encode_frame(
            MessageType.IIS3DWB_FIFO,
            1,
            timestamp_word + accel_word,
            timestamp_us=1_000_000,
            item_count=2,
        )
    )[0]
    second = parser.feed(
        encode_frame(
            MessageType.IIS3DWB_FIFO,
            2,
            accel_word,
            timestamp_us=1_000_100,
            item_count=1,
        )
    )[0]

    assert first.iis_samples is not None
    assert second.iis_samples is not None
    assert first.iis_samples[0].timestamp_us == pytest.approx(1_000_000.0)
    assert second.iis_samples[0].timestamp_us == pytest.approx(1_000_037.5)


def test_iis_sensor_timestamp_wrap_stays_on_mcu_timeline() -> None:
    accel_word = bytes([2 << 3]) + struct.pack("<hhh", 1, 2, 3)
    before_wrap = bytes([4 << 3]) + struct.pack("<I", 0xFFFFFFF0) + b"\x00\x00"
    after_wrap = bytes([4 << 3]) + struct.pack("<I", 0x00000010) + b"\x00\x00"
    parser = StreamParser()

    frame = parser.feed(
        encode_frame(
            MessageType.IIS3DWB_FIFO,
            1,
            before_wrap + accel_word + after_wrap + accel_word,
            timestamp_us=2_000_800,
            item_count=4,
        )
    )[0]

    assert frame.iis_samples is not None
    assert [sample.timestamp_us for sample in frame.iis_samples] == pytest.approx(
        [2_000_000.0, 2_000_800.0]
    )
