from sensor_host.tools.acceptance_models import AcceptanceReport

import struct
import zlib

from sensor_host.protocol import MessageType, StreamParser
from sensor_host.protocol.sdf1 import HEADER_SIZE, MAGIC, VERSION


def _status_frame(payload: bytes, sequence: int = 1) -> bytes:
    """Encode a CRC-valid V1 STATUS frame wrapping a 64-byte status payload."""
    header = struct.pack(
        "<4sBBHHHIQHH",
        MAGIC,
        VERSION,
        int(MessageType.STATUS),
        0,
        HEADER_SIZE,
        len(payload),
        sequence,
        0,
        1,
        0,
    )
    body = header + payload
    return body + struct.pack("<I", zlib.crc32(body) & 0xFFFFFFFF)


def test_status_v1_offset24_is_transport_drops() -> None:
    """C4 guard: transport_drops stays at byte offset 24 in the V1 STATUS.

    Normal real-time running must not inflate this compatible counter (live
    newest-wins drops and quiesce-discarded replicas are counted separately in
    DROPS_IIS/DROPS_JY), so the binary layout must keep decoding offset 24 as
    transport_drops and offset 20 as source_drops.
    """
    payload = bytearray(64)
    payload[0] = 1  # status_version
    struct.pack_into("<I", payload, 20, 7)  # source_drops
    struct.pack_into("<I", payload, 24, 11)  # transport_drops

    parser = StreamParser()
    frames = parser.feed(_status_frame(bytes(payload)))

    assert len(frames) == 1
    status = frames[0].status
    assert status is not None
    assert status.status_version == 1
    assert status.source_drops == 7
    assert status.transport_drops == 11


def test_acceptance_report_requires_zero_integrity_errors() -> None:
    report = AcceptanceReport(
        duration_s=1800.0,
        bytes_received=350_000_000,
        frames=100_000,
        crc_errors=0,
        sequence_gaps=0,
        source_drop_delta=0,
        transport_drop_delta=0,
        fifo_overrun_delta=0,
        recorder_bytes=350_000_000,
        replay_frames=100_000,
    )

    assert report.passed
    assert not report.with_updates(crc_errors=1).passed
    assert not report.with_updates(replay_crc_errors=1).passed
    assert not report.with_updates(replay_frames=99_999).passed


def test_acceptance_report_requires_lossless_recording() -> None:
    report = AcceptanceReport(
        duration_s=300.0,
        bytes_received=10_000,
        frames=100,
        crc_errors=0,
        sequence_gaps=0,
        source_drop_delta=0,
        transport_drop_delta=0,
        fifo_overrun_delta=0,
        recorder_bytes=9_999,
        replay_frames=100,
    )

    assert not report.passed
