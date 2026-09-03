import argparse
from dataclasses import replace

import pytest

from sensor_host.tools.realtime_archive_models import (
    CdcExportAcceptance,
    InterruptedExportAcceptance,
    LiveAcceptance,
    OverwriteAcceptance,
    UartExportAcceptance,
    sequence_lag,
)
from host.tools.realtime_archive_acceptance import AcceptanceSession, _parse_state


def test_state_parser_exposes_storage_readiness() -> None:
    parsed = _parse_state(
        "+STATE:IDLE\r\n"
        "+UUID:550e8400-e29b-41d4-a716-446655440000,SOURCE=DERIVED\r\n"
        "+SD:USED=0,CAPACITY=100,PENDING_FRAMES=0,RETAINED_CHUNKS=0,"
        "RETAINED_FRAMES=0,OVERWRITTEN_CHUNKS=0,OVERWRITTEN_FRAMES=0,"
        "READY=1,FORMAT_REQUIRED=0\r\n"
        "+LIVE:TARGET=UART,DROPS_IIS=0,DROPS_JY=0,"
        "LAST_ROUTED_SEQUENCE=0,LAST_COMPLETED_SEQUENCE=0\r\nOK\r\n"
    )
    assert parsed["sd_ready"] is True
    assert parsed["sd_format_required"] is False
    assert parsed["live_target"] == "UART"
    assert parsed["drops_iis"] == 0
    assert parsed["drops_jy"] == 0
    assert parsed["last_routed_sequence"] == 0
    assert parsed["last_completed_sequence"] == 0


def test_state_parser_exposes_live_target_cdc() -> None:
    parsed = _parse_state(
        "+STATE:ACQUIRE\r\n"
        "+UUID:550e8400-e29b-41d4-a716-446655440000,SOURCE=CONFIGURED\r\n"
        "+SD:USED=1024,CAPACITY=2048,PENDING_FRAMES=5,RETAINED_CHUNKS=2,"
        "RETAINED_FRAMES=10,OVERWRITTEN_CHUNKS=0,OVERWRITTEN_FRAMES=0,"
        "READY=1,FORMAT_REQUIRED=0\r\n"
        "+LIVE:TARGET=CDC,DROPS_IIS=3,DROPS_JY=1,"
        "LAST_ROUTED_SEQUENCE=500,LAST_COMPLETED_SEQUENCE=490\r\nOK\r\n"
    )
    assert parsed["live_target"] == "CDC"
    assert parsed["drops_iis"] == 3
    assert parsed["drops_jy"] == 1
    assert parsed["last_routed_sequence"] == 500
    assert parsed["last_completed_sequence"] == 490


def test_sequence_lag_wraparound() -> None:
    assert sequence_lag(100, 50) == 50
    assert sequence_lag(0, 0) == 0
    # Wraparound: routed=2, completed=0xFFFFFFFE -> lag = 4
    assert sequence_lag(2, 0xFFFFFFFE) == 4
    assert sequence_lag(0xFFFFFFFF, 0xFFFFFFFF) == 0


def _live(target: str = "UART", **overrides: object) -> LiveAcceptance:
    """Build a passing LiveAcceptance for ``target`` with optional overrides."""
    fields: dict[str, object] = dict(
        live_target=target,
        target_frames=200,
        nontarget_frames=0,
        max_sequence_lag=8,
        target_crc_errors=0,
        nontarget_crc_errors=0,
        header_errors=0,
        length_errors=0,
        payload_errors=0,
        physical_tx_error_delta=0,
        drops_iis_delta=0,
        drops_jy_delta=0,
        source_drop_delta=0,
        stop_latency_s=0.5,
        post_stop_sensor_frames=0,
        nontarget_at_probe=True,
    )
    fields.update(overrides)
    return LiveAcceptance(**fields)  # type: ignore[arg-type]


def test_live_acceptance_rejects_each_required_invariant() -> None:
    accepted = _live("UART")
    assert accepted.passed
    for field, value in {
        "live_target": "INVALID",
        "target_frames": 0,
        "nontarget_frames": 1,
        "max_sequence_lag": 65,
        "target_crc_errors": 1,
        "nontarget_crc_errors": 1,
        "header_errors": 1,
        "length_errors": 1,
        "payload_errors": 1,
        "physical_tx_error_delta": 1,
        "source_drop_delta": 1,
        "stop_latency_s": 2.01,
        "post_stop_sensor_frames": 1,
        "nontarget_at_probe": False,
    }.items():
        assert not replace(accepted, **{field: value}).passed


def test_c7_uart_target_allows_newest_wins_live_drops() -> None:
    # UART live target tolerates shared live-drops (newest-wins backpressure)
    # as long as source_drop, protocol and physical TX errors stay zero.
    assert _live("UART", drops_iis_delta=5, drops_jy_delta=3).passed


def test_c7_cdc_target_requires_zero_live_drops() -> None:
    assert _live("CDC").passed
    assert not _live("CDC", drops_iis_delta=1).passed
    assert not _live("CDC", drops_jy_delta=1).passed


def test_c5_parser_reports_format_required_structurally() -> None:
    parsed = _parse_state(
        "+STATE:IDLE\r\n"
        "+UUID:550e8400-e29b-41d4-a716-446655440000,SOURCE=DERIVED\r\n"
        "+SD:USED=0,CAPACITY=100,PENDING_FRAMES=0,RETAINED_CHUNKS=0,"
        "RETAINED_FRAMES=0,OVERWRITTEN_CHUNKS=0,OVERWRITTEN_FRAMES=0,"
        "READY=0,FORMAT_REQUIRED=1\r\n"
        "+LIVE:TARGET=UART,DROPS_IIS=0,DROPS_JY=0,"
        "LAST_ROUTED_SEQUENCE=0,LAST_COMPLETED_SEQUENCE=0\r\nOK\r\n"
    )
    assert parsed["sd_ready"] is False
    assert parsed["sd_format_required"] is True


def test_c6_parser_flags_response_too_large() -> None:
    with pytest.raises(ValueError, match="RESPONSE_TOO_LARGE"):
        _parse_state("ERROR:RESPONSE_TOO_LARGE\r\n")


def test_d2_parser_flags_tx_busy_as_transient_diagnostic() -> None:
    """D2: ERROR:TX_BUSY (control buffer pool exhausted) is a transient
    diagnostic, not a generic incomplete-response failure."""
    with pytest.raises(ValueError, match="TX_BUSY"):
        _parse_state("ERROR:TX_BUSY\r\n")


class _FakePort:
    """Records every write so a test can assert a command was (not) re-sent."""

    def __init__(self) -> None:
        self.writes: list[bytes] = []

    def write(self, data: bytes) -> int:
        self.writes.append(data)
        return len(data)

    def flush(self) -> None:
        pass


class _FakeReader:
    """Always returns the same scripted CLI text from cli_since()."""

    def __init__(self, reply: str) -> None:
        self._reply = reply

    def snapshot(self) -> dict[str, int]:
        return {"cli": 0}

    def cli_since(self, marker: int) -> str:
        return self._reply


def _fake_session(tmp_path, reply: str) -> tuple[AcceptanceSession, _FakePort]:
    """Build an AcceptanceSession with fake CDC/UART ports that emit ``reply``."""
    arguments = argparse.Namespace(output=tmp_path / "out.json")
    session = AcceptanceSession(arguments)
    port = _FakePort()
    reader = _FakeReader(reply)
    session.cdc_port = port
    session.cdc = reader  # type: ignore[assignment]
    session.uart_port = port
    session.uart = reader  # type: ignore[assignment]
    return session, port


def test_w2_non_idempotent_command_never_resends_on_tx_busy(tmp_path) -> None:
    """W-2: AT+STOP with idempotent=False must NOT be re-sent on ERROR:TX_BUSY.

    TX_BUSY means the command already executed and only its reply failed to
    transmit; re-sending AT+STOP would be rejected as ERROR:STATE and turn a
    healthy run into a false failure.  command() must raise a clear structured
    RuntimeError after exactly one write.
    """
    session, port = _fake_session(tmp_path, "ERROR:TX_BUSY\r\n")
    with pytest.raises(RuntimeError, match="NON-idempotent"):
        session.command("AT+STOP", idempotent=False)
    assert len(port.writes) == 1


def test_w2_non_idempotent_command_never_resends_on_busy(tmp_path) -> None:
    """W-2: same no-resend guarantee for ERROR:BUSY on AT+SDCLEAR=CONFIRM."""
    session, port = _fake_session(tmp_path, "ERROR:BUSY\r\n")
    with pytest.raises(RuntimeError, match="NON-idempotent"):
        session.command("AT+SDCLEAR=CONFIRM", idempotent=False)
    assert len(port.writes) == 1


def test_w2_idempotent_command_still_backs_off_and_resends(tmp_path) -> None:
    """Contrast: idempotent commands keep the bounded busy-retry behaviour."""
    session, port = _fake_session(tmp_path, "ERROR:BUSY\r\n")
    with pytest.raises(RuntimeError, match="transiently busy"):
        session.command("AT+LIVESTREAM?", idempotent=True, busy_retries=1)
    assert len(port.writes) == 2  # initial send + 1 backoff re-send


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
