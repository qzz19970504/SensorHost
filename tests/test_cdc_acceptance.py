from sensor_host.tools.acceptance_models import AcceptanceReport
from sensor_host.tools.realtime_archive_models import LiveAcceptance

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


def test_status_v1_offset32_and_offset36_decode() -> None:
    """D1 guard: offset32 decodes as uart_dma_errors, offset36 as cdc_errors.

    The CDC physical-TX gate reads cdc_errors (offset36).  Before this round the
    firmware left it permanently 0, so the gate was a silent always-true.  This
    proves the decode chain surfaces non-zero offset32/offset36 values.
    """
    payload = bytearray(64)
    payload[0] = 1  # status_version
    struct.pack_into("<I", payload, 32, 5)  # uart_dma_errors
    struct.pack_into("<I", payload, 36, 9)  # cdc_errors

    parser = StreamParser()
    frames = parser.feed(_status_frame(bytes(payload)))

    assert len(frames) == 1
    status = frames[0].status
    assert status is not None
    assert status.status_version == 1
    assert status.uart_dma_errors == 5
    assert status.cdc_errors == 9


def _cdc_live(physical_tx_error_delta: int) -> LiveAcceptance:
    """A otherwise-passing CDC LiveAcceptance with the given offset36 delta."""
    return LiveAcceptance(
        live_target="CDC",
        target_frames=200,
        nontarget_frames=0,
        max_sequence_lag=8,
        target_crc_errors=0,
        nontarget_crc_errors=0,
        header_errors=0,
        length_errors=0,
        payload_errors=0,
        physical_tx_error_delta=physical_tx_error_delta,
        drops_iis_delta=0,
        drops_jy_delta=0,
        source_drop_delta=0,
        stop_latency_s=0.5,
        post_stop_sensor_frames=0,
        nontarget_at_probe=True,
    )


def test_cdc_physical_tx_gate_rejects_nonzero_offset36_delta() -> None:
    """MJ-D guard: a non-zero cdc_errors (offset36) delta must fail the CDC gate.

    End-to-end: decode two STATUS frames whose offset36 differs, derive
    physical_tx_error_delta exactly as the acceptance tool does for a CDC target,
    and assert the LiveAcceptance gate rejects it.  With offset36 equal the gate
    passes, proving the threshold is genuinely sensitive to cdc_errors rather
    than silently always-true (the pre-fix firmware left offset36 at 0).
    """
    def _cdc_errors(value: int) -> int:
        payload = bytearray(64)
        payload[0] = 1
        struct.pack_into("<I", payload, 36, value)
        frames = StreamParser().feed(_status_frame(bytes(payload)))
        status = frames[0].status
        assert status is not None
        return status.cdc_errors

    before = _cdc_errors(3)
    after = _cdc_errors(6)
    delta = after - before  # mirrors the realtime_archive_acceptance CDC path
    assert delta == 3
    assert not _cdc_live(delta).passed
    assert _cdc_live(0).passed
