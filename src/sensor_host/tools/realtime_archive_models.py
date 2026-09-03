"""Strict immutable result models for real-time and archive acceptance."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LiveAcceptance:
    uart_frames: int
    cdc_frames: int
    uart_max_sequence_lag: int
    uart_crc_errors: int
    cdc_crc_errors: int
    cdc_live_drop_delta: int
    source_drop_delta: int

    @property
    def passed(self) -> bool:
        return (
            self.uart_frames > 0
            and self.cdc_frames > 0
            and self.uart_max_sequence_lag <= 64
            and self.uart_crc_errors == 0
            and self.cdc_crc_errors == 0
            and self.cdc_live_drop_delta == 0
            and self.source_drop_delta == 0
        )


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
