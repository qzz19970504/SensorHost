"""Strict immutable result models for real-time and archive acceptance."""

from __future__ import annotations

from dataclasses import dataclass


def sequence_lag(routed: int, completed: int) -> int:
    """Unsigned 32-bit wraparound difference: routed - completed."""
    return (routed - completed) & 0xFFFFFFFF


@dataclass(frozen=True)
class LiveAcceptance:
    """Single-target live streaming acceptance (UART or CDC selected).

    C7 conditional thresholds:
    - CDC target: requires drops_iis_delta==0 and drops_jy_delta==0 (lossless).
    - UART target: allows live-drops (newest-wins is expected), but requires
      source_drop==0, all protocol errors==0, physical TX errors==0.
    Both require max_sequence_lag<=64, nontarget_frames==0, zero NEW active
    sensor frames after STOP's OK returns, and non-target AT probe success.

    C1 post-STOP gate semantics (false-negative fix): the firmware design
    explicitly allows the single in-flight live frame to complete naturally
    during the STOP handshake (it finishes before OK is returned); the
    live_inhibited latch guarantees no NEW active frame is emitted after OK.
    So ``post_stop_sensor_frames`` is the count of NEW sensor frames observed
    AFTER STOP's OK returns (hard gate, must be 0), and the frame that completes
    within the handshake window is reported separately as the soft diagnostic
    ``handshake_inflight_frames`` (expected <= 1) which never affects ``passed``.
    """

    live_target: str  # "UART" or "CDC"
    target_frames: int  # sensor frames on the selected link
    nontarget_frames: int  # sensor frames on the non-selected link (must be 0)
    max_sequence_lag: int  # max(routed - completed) observed, unsigned 32-bit
    target_crc_errors: int
    nontarget_crc_errors: int
    header_errors: int  # parser header_errors delta on target link
    length_errors: int  # parser length_errors delta on target link
    payload_errors: int  # parser payload_errors delta on target link
    physical_tx_error_delta: int  # D1: UART target=offset32 uart_dma_errors,
    #                                  CDC target=offset36 cdc_errors (delta)
    drops_iis_delta: int  # shared IIS live-drop increment (snapshot diff)
    drops_jy_delta: int  # shared JY live-drop increment (snapshot diff)
    source_drop_delta: int
    stop_latency_s: float  # STOP dual-completion latency
    post_stop_sensor_frames: int  # C1: NEW sensor frames after STOP's OK (==0)
    nontarget_at_probe: bool  # C8: non-target link responds to AT/AT+STATE?
    # Soft diagnostic (NOT a gate): active sensor frames during the handshake
    # window (AT+STOP written -> OK received).  Firmware allows the single
    # in-flight frame to complete here, so the expected value is <= 1.
    handshake_inflight_frames: int = 0

    @property
    def passed(self) -> bool:
        common = (
            self.live_target in ("UART", "CDC")
            and self.target_frames > 0
            and self.nontarget_frames == 0
            and self.max_sequence_lag <= 64
            and self.target_crc_errors == 0
            and self.nontarget_crc_errors == 0
            and self.header_errors == 0
            and self.length_errors == 0
            and self.payload_errors == 0
            and self.physical_tx_error_delta == 0
            and self.source_drop_delta == 0
            and 0.0 <= self.stop_latency_s <= 2.0
            and self.post_stop_sensor_frames == 0
            and self.nontarget_at_probe
        )
        if not common:
            return False
        # C7: CDC requires zero live-drops; UART allows newest-wins drops
        if self.live_target == "CDC":
            return self.drops_iis_delta == 0 and self.drops_jy_delta == 0
        return True


@dataclass(frozen=True)
class OverwriteAcceptance:
    duration_s: float
    remained_acquiring: bool
    overwritten_chunks_delta: int
    overwritten_frames_delta: int
    source_drop_delta: int
    sd_errors: int
    transport_errors: int
    stop_latency_s: float
    stopped_idle: bool
    retained_frames: int

    @property
    def passed(self) -> bool:
        return (
            self.duration_s > 0.0
            and self.remained_acquiring
            and self.overwritten_chunks_delta > 0
            and self.overwritten_frames_delta > 0
            and self.source_drop_delta == 0
            and self.sd_errors == 0
            and self.transport_errors == 0
            and 0.0 <= self.stop_latency_s <= 2.0
            and self.stopped_idle
            and self.retained_frames > 0
        )


@dataclass(frozen=True)
class UartExportAcceptance:
    frames: int
    iis_frames: int
    jy_frames: int
    expected_uuid: str
    observed_uuids: tuple[str, ...]
    archive_flag_errors: int
    crc_errors: int
    length_errors: int
    payload_errors: int
    duplicate_frames: int
    missing_after_dedup: int
    terminal_seen: bool
    storage_empty: bool
    wrong_route_frames: int

    @property
    def passed(self) -> bool:
        return (
            self.frames > 0
            and self.iis_frames > 0
            and self.jy_frames > 0
            and bool(self.expected_uuid)
            and self.observed_uuids == (self.expected_uuid,)
            and self.archive_flag_errors == 0
            and self.crc_errors == 0
            and self.length_errors == 0
            and self.payload_errors == 0
            and self.missing_after_dedup == 0
            and self.terminal_seen
            and self.storage_empty
            and self.wrong_route_frames == 0
        )


@dataclass(frozen=True)
class CdcExportAcceptance(UartExportAcceptance):
    control_responses_valid: bool
    faster_than_uart: bool

    @property
    def passed(self) -> bool:
        return (
            super().passed
            and self.control_responses_valid
            and self.faster_than_uart
        )


@dataclass(frozen=True)
class InterruptedExportAcceptance:
    first_export_frames: int
    resumed_export_frames: int
    duplicate_frames: int
    missing_after_dedup: int
    uuid_mismatches: int
    archive_flag_errors: int
    crc_errors: int
    length_errors: int
    payload_errors: int
    resumed_acquire: bool
    final_storage_empty: bool

    @property
    def passed(self) -> bool:
        return (
            self.first_export_frames > 0
            and self.resumed_export_frames > 0
            and self.duplicate_frames > 0
            and self.missing_after_dedup == 0
            and self.uuid_mismatches == 0
            and self.archive_flag_errors == 0
            and self.crc_errors == 0
            and self.length_errors == 0
            and self.payload_errors == 0
            and self.resumed_acquire
            and self.final_storage_empty
        )
