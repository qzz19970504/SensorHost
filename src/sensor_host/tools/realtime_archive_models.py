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
    - CDC target: requires drops_iis_delta==0 and drops_jy_delta==0 (lossless,
      USB bandwidth is sufficient so zero live-drop is expected).
    - UART target: allows live-drops (newest-wins is expected), but requires
      source_drop==0, all protocol errors==0, physical TX errors==0.
    Both require nontarget_frames==0, zero NEW active sensor frames after STOP's
    OK returns, and (when applicable) non-target AT probe success.

    115200 newest-wins freshness model (user-approved requirement change):
    the real bench receives device UART through an ESP32 gateway at 115200.
    The UART/CDC live link only guarantees freshness (newest-wins delivers the
    latest frame; heavy live-drop under insufficient bandwidth is expected and
    allowed), while the SD archive guarantees completeness (source_drop==0).
    Therefore ``max_sequence_lag`` is NO LONGER a hard gate: at 115200 a large
    routed-vs-completed lag is a physical consequence of newest-wins backpressure,
    not a defect.  It is retained as a reported freshness diagnostic alongside
    the delivered frame rate (target_frames/duration), but never affects
    ``passed``.  The genuine invariants (source_drop==0, delivered-frame
    CRC/header/length/payload==0, physical TX errors==0, nontarget_frames==0,
    STOP dual-completion latency, post-OK zero frames, CDC live-drop==0) remain
    hard gates; sampling rate is never reduced to accommodate the bandwidth.

    C1 post-STOP gate semantics (false-negative fix): the firmware design
    explicitly allows the single in-flight live frame to complete naturally
    during the STOP handshake (it finishes before OK is returned); the
    live_inhibited latch guarantees no NEW active frame is emitted after OK.
    So ``post_stop_sensor_frames`` is the count of NEW sensor frames observed
    AFTER STOP's OK returns (hard gate, must be 0), and the frame that completes
    within the handshake window is reported separately as the soft diagnostic
    ``handshake_inflight_frames`` (expected <= 1) which never affects ``passed``.

    Unidirectional-UART bench: the current bench only wires the UART upload
    direction (device->host); host->device UART is physically absent, so no AT
    command can be sent to UART.  When the non-target link is UART and
    ``nontarget_at_probe_applicable`` is False, the C8 non-target AT probe is
    marked N/A and does NOT gate ``passed`` (it cannot be sent, not a failure);
    the non-target link is still enforced silent via ``nontarget_frames==0``
    (passive monitoring).
    """

    live_target: str  # "UART" or "CDC"
    target_frames: int  # sensor frames on the selected link
    nontarget_frames: int  # sensor frames on the non-selected link (must be 0)
    # Freshness DIAGNOSTIC only (not a gate) under the 115200 newest-wins model:
    # max(routed - completed) observed, unsigned 32-bit wraparound.
    max_sequence_lag: int
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
    # C8 applicability: False when the non-target link is UART and host->device
    # UART is physically absent on the bench, so the AT probe is N/A and must
    # not gate ``passed`` (the link is still enforced silent via nontarget_frames).
    nontarget_at_probe_applicable: bool = True

    @property
    def passed(self) -> bool:
        common = (
            self.live_target in ("UART", "CDC")
            and self.target_frames > 0
            and self.nontarget_frames == 0
            # 115200 newest-wins model: max_sequence_lag is a freshness
            # diagnostic, NOT a hard gate (user-approved requirement change).
            and self.target_crc_errors == 0
            and self.nontarget_crc_errors == 0
            and self.header_errors == 0
            and self.length_errors == 0
            and self.payload_errors == 0
            and self.physical_tx_error_delta == 0
            and self.source_drop_delta == 0
            and 0.0 <= self.stop_latency_s <= 2.0
            and self.post_stop_sensor_frames == 0
            # C8: probe gates only when applicable (unidirectional-UART bench
            # marks it N/A because host->device UART cannot be sent).
            and (self.nontarget_at_probe or not self.nontarget_at_probe_applicable)
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
