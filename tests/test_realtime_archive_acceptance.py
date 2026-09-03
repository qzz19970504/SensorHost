from dataclasses import replace

from sensor_host.tools.realtime_archive_models import (
    CdcExportAcceptance,
    InterruptedExportAcceptance,
    LiveAcceptance,
    OverwriteAcceptance,
    UartExportAcceptance,
)
from host.tools.realtime_archive_acceptance import _parse_state


def test_state_parser_exposes_storage_readiness() -> None:
    parsed = _parse_state(
        "+STATE:IDLE\r\n"
        "+UUID:550e8400-e29b-41d4-a716-446655440000,SOURCE=DERIVED\r\n"
        "+SD:USED=0,CAPACITY=100,PENDING_FRAMES=0,RETAINED_CHUNKS=0,"
        "RETAINED_FRAMES=0,OVERWRITTEN_CHUNKS=0,OVERWRITTEN_FRAMES=0,"
        "READY=1,FORMAT_REQUIRED=0\r\n"
        "+LIVE_DROPS:UART_IIS=0,UART_JY=0,CDC=0\r\nOK\r\n"
    )
    assert parsed["sd_ready"] is True
    assert parsed["sd_format_required"] is False


def test_live_acceptance_rejects_each_required_invariant() -> None:
    accepted = LiveAcceptance(20, 200, 8, 0, 0, 0, 0)
    assert accepted.passed
    for field, value in {
        "uart_frames": 0,
        "cdc_frames": 0,
        "uart_max_sequence_lag": 65,
        "uart_crc_errors": 1,
        "cdc_crc_errors": 1,
        "cdc_live_drop_delta": 1,
        "source_drop_delta": 1,
    }.items():
        assert not replace(accepted, **{field: value}).passed


def test_overwrite_requires_wrap_without_errors_and_bounded_stop() -> None:
    accepted = OverwriteAcceptance(
        duration_s=1800.0,
        remained_acquiring=True,
        overwritten_chunks_delta=1,
        overwritten_frames_delta=12,
        source_drop_delta=0,
        sd_errors=0,
        transport_errors=0,
        stop_latency_s=0.8,
        stopped_idle=True,
        retained_frames=100,
    )
    assert accepted.passed
    for field, value in {
        "duration_s": 0.0,
        "remained_acquiring": False,
        "overwritten_chunks_delta": 0,
        "overwritten_frames_delta": 0,
        "source_drop_delta": 1,
        "sd_errors": 1,
        "transport_errors": 1,
        "stop_latency_s": 2.01,
        "stopped_idle": False,
        "retained_frames": 0,
    }.items():
        assert not replace(accepted, **{field: value}).passed


def _uart_export() -> UartExportAcceptance:
    return UartExportAcceptance(
        frames=20,
        iis_frames=18,
        jy_frames=2,
        expected_uuid="550e8400-e29b-41d4-a716-446655440000",
        observed_uuids=("550e8400-e29b-41d4-a716-446655440000",),
        archive_flag_errors=0,
        crc_errors=0,
        length_errors=0,
        payload_errors=0,
        duplicate_frames=0,
        missing_after_dedup=0,
        terminal_seen=True,
        storage_empty=True,
        wrong_route_frames=0,
    )


def test_uart_export_requires_identity_types_integrity_route_and_empty_sd() -> None:
    accepted = _uart_export()
    assert accepted.passed
    for field, value in {
        "frames": 0,
        "iis_frames": 0,
        "jy_frames": 0,
        "observed_uuids": ("00000000-0000-0000-0000-000000000000",),
        "archive_flag_errors": 1,
        "crc_errors": 1,
        "length_errors": 1,
        "payload_errors": 1,
        "missing_after_dedup": 1,
        "terminal_seen": False,
        "storage_empty": False,
        "wrong_route_frames": 1,
    }.items():
        assert not replace(accepted, **{field: value}).passed


def test_cdc_export_also_requires_valid_control_multiplexing_and_speedup() -> None:
    accepted = CdcExportAcceptance(
        **{
            field: getattr(_uart_export(), field)
            for field in _uart_export().__dataclass_fields__
            if field != "wrong_route_frames"
        },
        wrong_route_frames=0,
        control_responses_valid=True,
        faster_than_uart=True,
    )
    assert accepted.passed
    assert not replace(accepted, control_responses_valid=False).passed
    assert not replace(accepted, faster_than_uart=False).passed


def test_interrupted_export_allows_duplicates_but_never_missing_frames() -> None:
    accepted = InterruptedExportAcceptance(
        first_export_frames=7,
        resumed_export_frames=20,
        duplicate_frames=7,
        missing_after_dedup=0,
        uuid_mismatches=0,
        archive_flag_errors=0,
        crc_errors=0,
        length_errors=0,
        payload_errors=0,
        resumed_acquire=True,
        final_storage_empty=True,
    )
    assert accepted.passed
    assert not replace(accepted, duplicate_frames=0).passed
    assert not replace(accepted, missing_after_dedup=1).passed
    assert not replace(accepted, resumed_acquire=False).passed
