import argparse
import time
from dataclasses import replace
from pathlib import Path

import pytest

from sensor_host.tools.realtime_archive_models import (
    CdcExportAcceptance,
    InterruptedExportAcceptance,
    LiveAcceptance,
    OverwriteAcceptance,
    UartExportAcceptance,
    sequence_lag,
)
from host.tools.realtime_archive_acceptance import (
    AcceptanceSession,
    PortReader,
    _parse_state,
    _select_poll_interval,
)


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


def test_115200_uart_target_large_lag_is_diagnostic_not_a_failure() -> None:
    """User-approved 115200 newest-wins model: a large routed-vs-completed lag is
    a physical consequence of newest-wins backpressure at 115200, NOT a defect.
    max_sequence_lag must no longer gate passed, yet it is still reported as
    freshness evidence, and UART live-drops remain allowed."""
    laggy = _live("UART", max_sequence_lag=5000, drops_iis_delta=120,
                  drops_jy_delta=80)
    assert laggy.passed
    assert laggy.max_sequence_lag == 5000  # still recorded as evidence


def test_115200_lag_not_gating_but_real_invariants_still_fail() -> None:
    """Removing the lag gate must NOT weaken the real gates: a large lag alone
    passes, but source_drop / CRC / physical-TX still fail the run."""
    assert _live("UART", max_sequence_lag=9999).passed
    assert not _live("UART", max_sequence_lag=9999, source_drop_delta=1).passed
    assert not _live("UART", max_sequence_lag=9999, target_crc_errors=1).passed
    assert not _live("UART", max_sequence_lag=9999,
                     physical_tx_error_delta=1).passed


def test_cdc_target_still_requires_zero_live_drop_under_large_lag() -> None:
    """C7 unchanged: CDC (USB bandwidth sufficient) still requires zero live-drop
    even though lag is no longer a gate."""
    assert _live("CDC", max_sequence_lag=5000).passed
    assert not _live("CDC", max_sequence_lag=5000, drops_iis_delta=1).passed
    assert not _live("CDC", max_sequence_lag=5000, drops_jy_delta=1).passed


def test_unidirectional_uart_nontarget_probe_na_does_not_fail() -> None:
    """Unidirectional-UART bench: for a CDC data target the non-target link is
    UART, whose host->device direction is physically absent, so the C8 AT probe
    is N/A (nontarget_at_probe_applicable=False) and must NOT gate passed.  The
    non-target link is still enforced silent via nontarget_frames==0."""
    assert _live("CDC", nontarget_at_probe=False,
                 nontarget_at_probe_applicable=False).passed
    # ... but a non-silent UART non-target still fails (passive monitoring gate).
    assert not _live("CDC", nontarget_at_probe=False,
                     nontarget_at_probe_applicable=False,
                     nontarget_frames=1).passed


def test_nontarget_probe_still_gates_when_applicable() -> None:
    """When the probe IS applicable (live-uart non-target CDC, or UART TX wired),
    a failed non-target AT probe still fails the run."""
    assert not _live("UART", nontarget_at_probe=False,
                     nontarget_at_probe_applicable=True).passed
    assert _live("UART", nontarget_at_probe=True,
                 nontarget_at_probe_applicable=True).passed


def test_c1_handshake_inflight_frame_is_not_a_post_stop_failure() -> None:
    """False-negative fix: the firmware allows the single in-flight live frame to
    complete during the STOP handshake (before OK returns).  The hard C1 gate
    only counts NEW frames AFTER OK, so a handshake_inflight_frames==1 with
    post_stop_sensor_frames==0 must PASS (this is exactly the healthy case that
    the old pre-AT+STOP baseline mis-counted as post_stop>=1).
    """
    assert _live("UART", post_stop_sensor_frames=0,
                 handshake_inflight_frames=1).passed
    # handshake_inflight_frames is a soft diagnostic and never flips passed,
    # even for the (unexpected) >1 case: it must not re-introduce a false fail.
    assert _live("UART", post_stop_sensor_frames=0,
                 handshake_inflight_frames=2).passed


def test_c1_new_active_frame_after_stop_ok_still_fails() -> None:
    """Real leak guard: an active sensor frame emitted AFTER STOP's OK returns
    (live_inhibited latch failed) must FAIL regardless of the handshake diag."""
    assert not _live("UART", post_stop_sensor_frames=1,
                     handshake_inflight_frames=0).passed
    assert not _live("CDC", post_stop_sensor_frames=1,
                     handshake_inflight_frames=1).passed


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


def test_parse_state_extracts_diag_fields_when_present() -> None:
    """+DIAG telemetry (firmware >= 180776a) is parsed into diag_* fields."""
    parsed = _parse_state(
        "+STATE:ACQUIRE\r\n"
        "+UUID:550e8400-e29b-41d4-a716-446655440000,SOURCE=DERIVED\r\n"
        "+SD:USED=10,CAPACITY=100,PENDING_FRAMES=2,RETAINED_CHUNKS=1,"
        "RETAINED_FRAMES=5,OVERWRITTEN_CHUNKS=0,OVERWRITTEN_FRAMES=0,"
        "READY=1,FORMAT_REQUIRED=0\r\n"
        "+LIVE:TARGET=UART,DROPS_IIS=3,DROPS_JY=1,"
        "LAST_ROUTED_SEQUENCE=100,LAST_COMPLETED_SEQUENCE=90\r\n"
        "+DIAG:POOL_FAIL=7,INGRESS_DROP=2,NOSTORE_DROP=0,POOL_MIN=1,"
        "INGRESS_PEAK=6,SD_STALL_MS=67,CDC_LIVE=5,CDC_CTRL=1,"
        "CDC_EXPORT=0\r\n"
        "+STOP_REASON:NONE\r\nOK\r\n"
    )
    assert parsed["diag_pool_fail"] == 7
    assert parsed["diag_ingress_drop"] == 2
    assert parsed["diag_nostore_drop"] == 0
    assert parsed["diag_pool_min"] == 1
    assert parsed["diag_ingress_peak"] == 6
    assert parsed["diag_sd_stall_ms"] == 67
    assert parsed["diag_cdc_live"] == 5
    assert parsed["diag_cdc_ctrl"] == 1
    assert parsed["diag_cdc_export"] == 0
    # Sum CDC partitions == offset36 equivalent.
    assert (parsed["diag_cdc_live"] + parsed["diag_cdc_ctrl"]
            + parsed["diag_cdc_export"]) == 6


def test_parse_state_graceful_without_diag() -> None:
    """Older firmware without +DIAG: parsing succeeds, diag_* fields absent."""
    parsed = _parse_state(
        "+STATE:IDLE\r\n"
        "+UUID:550e8400-e29b-41d4-a716-446655440000,SOURCE=DERIVED\r\n"
        "+SD:USED=0,CAPACITY=100,PENDING_FRAMES=0,RETAINED_CHUNKS=0,"
        "RETAINED_FRAMES=0,OVERWRITTEN_CHUNKS=0,OVERWRITTEN_FRAMES=0,"
        "READY=1,FORMAT_REQUIRED=0\r\n"
        "+LIVE:TARGET=UART,DROPS_IIS=0,DROPS_JY=0,"
        "LAST_ROUTED_SEQUENCE=0,LAST_COMPLETED_SEQUENCE=0\r\nOK\r\n"
    )
    assert parsed["state"] == "IDLE"
    assert "diag_pool_fail" not in parsed


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


class _FakeSerialPort:
    """Emulates a serial port the reader thread drains in uneven OS-like bursts."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)

    @property
    def in_waiting(self) -> int:
        return len(self._chunks[0]) if self._chunks else 0

    def read(self, n: int = 1) -> bytes:
        if self._chunks:
            return self._chunks.pop(0)
        time.sleep(0.005)  # avoid a hot spin once the queue is drained
        return b""


def _wait_reader(reader: PortReader, predicate, timeout_s: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate(reader):
            return True
        time.sleep(0.01)
    return False


def test_uart_reader_thread_continuously_drains_without_changing_parse(tmp_path) -> None:
    """The UART endpoint is drained by a dedicated PortReader background thread,
    so the main thread polling CDC never blocks UART reads.  Feeding the shared
    golden stream through that thread in uneven OS-like bursts must yield exactly
    the same parse result as an in-order feed (no host-side byte loss / spurious
    CRC), proving the reader thread does not alter parsing."""
    repository_root = Path(__file__).resolve().parents[2]
    stream = (repository_root / "test" / "golden"
              / "stream_v1_frames.bin").read_bytes()
    chunks = [stream[i:i + 7] for i in range(0, len(stream), 7)]
    raw_path = tmp_path / "uart.sdf1"
    reader = PortReader(_FakeSerialPort(chunks), raw_path, counters_only=False,
                        decode_sensor_payload=True)
    reader.start()
    try:
        assert _wait_reader(
            reader,
            lambda r: (r.snapshot()["sensor_frames"] >= 2
                       and r.snapshot()["statuses"] >= 1
                       and r.snapshot()["cli"] >= 1))
        snapshot = reader.snapshot()
        assert snapshot["sensor_frames"] == 2
        assert snapshot["statuses"] == 1
        assert snapshot["cli"] == 1
        assert snapshot["parser"]["crc_errors"] == 0
        assert snapshot["parser"]["header_errors"] == 0
        assert snapshot["bytes"] == len(stream)
    finally:
        reader.stop()
    assert reader.error is None
    # Every drained byte was persisted to the raw capture.
    assert raw_path.read_bytes() == stream


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


# --- R2 refinement (a): sparse control polling when links are shared ---------


def test_state_poll_interval_sparse_when_control_shares_data_link() -> None:
    """live-cdc (control=cdc, target=CDC) shares one physical link, so polling is
    sparse (5 s) to avoid CDC IN endpoint contention that makes the device's
    live-frame CDC_Transmit_FS go BUSY and, past the retry budget, drop.  live-uart
    (control=cdc, target=UART) uses separate links, so dense (50 ms) is harmless.
    An explicit --state-poll-interval override always wins."""
    assert _select_poll_interval("cdc", "CDC") == 5.0
    assert _select_poll_interval("cdc", "UART") == 0.05
    assert _select_poll_interval("cdc", "CDC", 1.0) == 1.0
    assert _select_poll_interval("cdc", "UART", 2.5) == 2.5
    # Link comparison is case/whitespace insensitive.
    assert _select_poll_interval(" CDC ", "cdc") == 5.0


# --- R2 refinement (b)/(c): cross-link post_stop timing ----------------------


_VALID_STATE_REPLY = (
    "+STATE:IDLE\r\n"
    "+UUID:550e8400-e29b-41d4-a716-446655440000,SOURCE=DERIVED\r\n"
    "+SD:USED=0,CAPACITY=100,PENDING_FRAMES=0,RETAINED_CHUNKS=0,"
    "RETAINED_FRAMES=0,OVERWRITTEN_CHUNKS=0,OVERWRITTEN_FRAMES=0,"
    "READY=1,FORMAT_REQUIRED=0\r\n"
    "+LIVE:TARGET=UART,DROPS_IIS=0,DROPS_JY=0,"
    "LAST_ROUTED_SEQUENCE=0,LAST_COMPLETED_SEQUENCE=0\r\nOK\r\n"
)


class _ScheduledReader:
    """Fake reader whose sensor_frames/bytes follow a wall-clock schedule.

    ``schedule`` is a list of ``(delay_s, sensor_frames, bytes)`` milestones
    applied relative to construction; the reader reports the latest milestone
    whose delay has elapsed.  ``cli_since`` always returns a valid +STATE/OK
    reply so AT+STOP and AT+STATE? succeed on the first poll, modelling the fast
    CDC control link whose OK precedes the slow data-link tail frame.
    """

    def __init__(self, schedule: list[tuple[float, int, int]] | None = None) -> None:
        self._t0 = time.monotonic()
        self._schedule = sorted(schedule or [])

    def _current(self) -> tuple[int, int]:
        elapsed = time.monotonic() - self._t0
        sensor, nbytes = 0, 0
        for delay, sensor_at, bytes_at in self._schedule:
            if elapsed >= delay:
                sensor, nbytes = sensor_at, bytes_at
        return sensor, nbytes

    def snapshot(self) -> dict[str, int]:
        sensor, nbytes = self._current()
        return {"cli": 0, "statuses": 0, "sensor_frames": sensor, "bytes": nbytes}

    def cli_since(self, marker: int) -> str:
        return _VALID_STATE_REPLY

    def latest_status(self) -> object | None:
        return None

    def frames_since(self, marker: dict[str, int]) -> list:
        return []


def _quiet_session(tmp_path, uart_schedule, cdc_schedule=None) -> AcceptanceSession:
    """AcceptanceSession with separate scheduled UART/CDC readers + a fake port."""
    arguments = argparse.Namespace(output=tmp_path / "out.json")
    session = AcceptanceSession(arguments)
    port = _FakePort()
    session.cdc_port = port
    session.uart_port = port
    session.cdc = _ScheduledReader(cdc_schedule)  # type: ignore[assignment]
    session.uart = _ScheduledReader(uart_schedule)  # type: ignore[assignment]
    return session


def test_post_stop_tail_frame_after_fast_ok_then_quiet_is_not_counted(tmp_path) -> None:
    """Cross-link false-positive fix (live-uart): the STOP OK returns over the
    fast CDC control link while the last data frame is still shifting out on the
    slow UART wire, so the tail frame arrives AFTER OK.  stop_and_wait must wait
    for link quiescence before taking the baseline, so the tail frame is absorbed
    into the handshake window (handshake_inflight_frames==1) and post_stop stays
    0 -- NOT mis-counted as a post-OK leak (the R2 live-uart post_stop=1 bug)."""
    # Tail frame lands 0.06 s after OK (sensor 0->1, bytes 0->80), then silence.
    session = _quiet_session(tmp_path, uart_schedule=[(0.06, 1, 80)])
    session.stop_and_wait(via="cdc", post_stop_quiet_s=0.15)
    assert session.handshake_inflight_frame_count() == 1
    assert session.post_stop_sensor_frame_count(wait_s=0.15) == 0
    # The healthy model gate passes: post_stop==0 with a handshake tail frame.
    assert _live("UART", post_stop_sensor_frames=0,
                 handshake_inflight_frames=1).passed


def test_post_stop_new_frame_after_quiet_still_fails(tmp_path) -> None:
    """Real leak guard: a NEW active sensor frame emitted AFTER the links went
    quiet and the baseline was taken (live_inhibited latch failed) must still be
    counted by post_stop_sensor_frame_count so the C1 gate fails.  The tail frame
    at 0.06 s is absorbed into the handshake; the leak at 0.55 s is not."""
    session = _quiet_session(
        tmp_path, uart_schedule=[(0.06, 1, 80), (0.55, 2, 160)])
    session.stop_and_wait(via="cdc", post_stop_quiet_s=0.15)
    assert session.handshake_inflight_frame_count() == 1
    # Observation window reaches the 0.55 s leak milestone -> one post-OK frame.
    assert session.post_stop_sensor_frame_count(wait_s=0.6) == 1
    # And the model gate flips to failed with post_stop_sensor_frames==1.
    assert not _live("UART", post_stop_sensor_frames=1,
                     handshake_inflight_frames=1).passed
