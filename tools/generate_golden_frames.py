#!/usr/bin/env python3
"""Generate transport V1 golden frames independently from the C firmware."""

from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parent
GOLDEN_DIR = ROOT / "golden"
HEADER_SIZE = 28
DATA_HEADER_SIZE = 44
MAX_PAYLOAD_SIZE = 3577
DEVICE_UUID = bytes.fromhex("00112233445566778899aabbccddeeff")


def encode_frame(
    message_type: int,
    flags: int,
    sequence: int,
    timestamp_us: int,
    item_count: int,
    payload: bytes,
) -> bytes:
    if len(payload) > MAX_PAYLOAD_SIZE:
        raise ValueError("payload exceeds V1 limit")
    is_sensor = message_type in (0x01, 0x02)
    version = 2 if is_sensor else 1
    header_size = DATA_HEADER_SIZE if is_sensor else HEADER_SIZE
    header = struct.pack(
        "<4sBBHHHIQHH",
        b"SDF1",
        version,
        message_type,
        flags,
        header_size,
        len(payload),
        sequence,
        timestamp_us,
        item_count,
        0,
    )
    body = header + (DEVICE_UUID if is_sensor else b"") + payload
    return body + struct.pack("<I", zlib.crc32(body) & 0xFFFFFFFF)


def main() -> None:
    cases = [
        {
            "name": "iis3dwb_fifo",
            "message_type": 0x01,
            "flags": 0x0001,
            "sequence": 1,
            "timestamp_us": 1_000_000,
            "item_count": 2,
            "payload": bytes(range(14)),
        },
        {
            "name": "jy61pl_sample",
            "message_type": 0x02,
            "flags": 0,
            "sequence": 2,
            "timestamp_us": 1_000_100,
            "item_count": 1,
            "payload": struct.pack("<7h", 0x1234, -2, -32768, 32767, 0, 1, -32767),
        },
        {
            "name": "status",
            "message_type": 0x03,
            "flags": 0x0002,
            "sequence": 3,
            "timestamp_us": 1_000_200,
            "item_count": 1,
            "payload": bytes(range(64)),
        },
        {
            "name": "cli_response",
            "message_type": 0x04,
            "flags": 0,
            "sequence": 4,
            "timestamp_us": 1_000_300,
            "item_count": 1,
            "payload": b"transport=cdc\r\n",
        },
    ]

    binary = bytearray()
    manifest = {"protocol": "SDF1", "versions": [1, 2], "frames": []}
    for case in cases:
        frame = encode_frame(
            case["message_type"],
            case["flags"],
            case["sequence"],
            case["timestamp_us"],
            case["item_count"],
            case["payload"],
        )
        offset = len(binary)
        binary.extend(frame)
        manifest["frames"].append(
            {
                "name": case["name"],
                "offset": offset,
                "length": len(frame),
                "message_type": case["message_type"],
                "version": 2 if case["message_type"] in (0x01, 0x02) else 1,
                "device_uuid": (
                    "00112233-4455-6677-8899-aabbccddeeff"
                    if case["message_type"] in (0x01, 0x02)
                    else None
                ),
                "flags": case["flags"],
                "sequence": case["sequence"],
                "timestamp_us": case["timestamp_us"],
                "item_count": case["item_count"],
                "payload_hex": case["payload"].hex(),
                "crc32": struct.unpack("<I", frame[-4:])[0],
            }
        )

    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    (GOLDEN_DIR / "stream_v1_frames.bin").write_bytes(binary)
    (GOLDEN_DIR / "stream_v1_frames.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
