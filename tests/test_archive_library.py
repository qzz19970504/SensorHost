from __future__ import annotations

import json
import struct
import uuid
import zlib
from pathlib import Path

import pytest

from sensor_host.storage import archive_library
from sensor_host.storage.archive_library import build_playback_index, scan_exports


DEVICE_UUID = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")


def encode_iis_frame(
    sequence: int,
    timestamp_us: int,
    accel_count: int = 3,
    flags: int = 0x8000,
) -> bytes:
    payload = bytearray()
    payload += bytes([4 << 3]) + struct.pack("<I", timestamp_us // 25) + b"\x00\x00"
    for index in range(accel_count):
        payload += bytes([2 << 3]) + struct.pack(
            "<hhh", index + 1, index + 2, index + 3
        )
    header = (
        struct.pack(
            "<4sBBHHHIQHH",
            b"SDF1",
            2,
            1,
            flags,
            44,
            len(payload),
            sequence,
            timestamp_us,
            len(payload) // 7,
            0,
        )
        + DEVICE_UUID.bytes
    )
    content = header + bytes(payload)
    return content + struct.pack("<I", zlib.crc32(content) & 0xFFFFFFFF)


def encode_jy_frame(sequence: int, timestamp_us: int, flags: int = 0x8000) -> bytes:
    payload = struct.pack("<7h", 0, 0, 16384, 2500, 100, -200, 300)
    header = (
        struct.pack(
            "<4sBBHHHIQHH",
            b"SDF1",
            2,
            2,
            flags,
            44,
            len(payload),
            sequence,
            timestamp_us,
            1,
            0,
        )
        + DEVICE_UUID.bytes
    )
    content = header + payload
    return content + struct.pack("<I", zlib.crc32(content) & 0xFFFFFFFF)


def archive_stream() -> bytes:
    stream = b""
    for index in range(4):
        stream += encode_iis_frame(index + 1, 1_000_000 + index * 1_000_000)
    stream += encode_jy_frame(5, 4_000_000)
    return stream


def write_archive(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(archive_stream())
    return path


def test_scan_exports_reads_sidecar_and_falls_back_without_it(tmp_path) -> None:
    root = tmp_path / "exports"
    with_sidecar = write_archive(
        root / "20260101T000000Z" / "node-a" / "export-001.sdf1"
    )
    with_sidecar.with_suffix(".json").write_text(
        json.dumps(
            {
                "format": "SDF1_ARCHIVE_EXPORT",
                "started_utc": "2026-01-01T00:00:00+00:00",
                "ended_utc": "2026-01-01T00:05:00+00:00",
                "bytes_written": 4321,
                "status": "complete",
                "alias": "North Motor",
                "uuid": str(DEVICE_UUID),
            }
        ),
        encoding="utf-8",
    )
    bare = write_archive(root / "20260102T000000Z" / "node-b" / "export-001.sdf1")

    entries = scan_exports(root)

    assert [entry.name for entry in entries] == [
        "export-001.sdf1",
        "export-001.sdf1",
    ]
    first = entries[0]
    assert first.path == bare
    assert first.status == "unknown"
    assert first.bytes_written == bare.stat().st_size
    assert first.started_utc
    second = entries[1]
    assert second.path == with_sidecar
    assert second.started_utc == "2026-01-01T00:00:00+00:00"
    assert second.bytes_written == 4321
    assert second.status == "complete"
    assert second.alias == "North Motor"


def test_scan_exports_missing_root_is_empty(tmp_path) -> None:
    assert scan_exports(tmp_path / "does-not-exist") == []


def test_delete_export_removes_archive_and_sidecar(tmp_path) -> None:
    path = write_archive(tmp_path / "exports" / "export-001.sdf1")
    sidecar = path.with_suffix(".json")
    sidecar.write_text('{"status": "aborted"}', encoding="utf-8")

    archive_library.delete_export(path)

    assert not path.exists()
    assert not sidecar.exists()


def test_delete_export_rejects_non_archive_file(tmp_path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("keep me", encoding="utf-8")

    with pytest.raises(ValueError, match="SDF1 archive"):
        archive_library.delete_export(path)

    assert path.exists()


def test_build_playback_index_counts_samples_and_duration(tmp_path) -> None:
    path = write_archive(tmp_path / "export.sdf1")

    index = build_playback_index(path)

    assert index.total_samples == 12
    assert index.duration_s == pytest.approx(3.0)
    assert index.sample_rate_hz == pytest.approx(4.0)
    assert index.offsets.size == 5
    assert list(index.kinds) == [1, 1, 1, 1, 2]
    assert list(index.cum_samples) == [3, 6, 9, 12, 12]
    assert index.first_timestamp_us == pytest.approx(1_000_000)
    assert index.last_timestamp_us == pytest.approx(4_000_000)


def test_offset_for_time_targets_frame_at_or_before(tmp_path) -> None:
    index = build_playback_index(write_archive(tmp_path / "export.sdf1"))

    assert index.offset_for_time(0.0) == index.offsets[0]
    assert index.offset_for_time(2.5) == index.offsets[2]
    assert index.offset_for_time(99.0) == index.offsets[4]


def test_truncated_tail_does_not_add_phantom_frames(tmp_path) -> None:
    path = tmp_path / "export.sdf1"
    path.write_bytes(archive_stream() + encode_iis_frame(9, 9_000_000)[:10])

    index = build_playback_index(path)

    assert index.offsets.size == 5
    assert index.total_samples == 12
