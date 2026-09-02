"""Compare UART-authoritative and CDC-mirrored SDF1 sensor frames."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sensor_host.protocol import Frame, MessageType


_SENSOR_TYPES = {MessageType.IIS3DWB_FIFO, MessageType.JY61PL_SAMPLE}


@dataclass(frozen=True)
class DualOutputResult:
    uart_sensor_frames: int
    cdc_sensor_frames: int
    matched_frames: int
    uart_only_sequences: tuple[int, ...]
    cdc_only_sequences: tuple[int, ...]
    content_mismatches: tuple[int, ...]


def _fingerprint(frame: Frame) -> tuple[object, ...]:
    return (
        frame.message_type,
        frame.flags,
        frame.sequence,
        frame.timestamp_us,
        frame.item_count,
        frame.payload,
    )


def compare_sensor_frames(
    uart_frames: Iterable[Frame],
    cdc_frames: Iterable[Frame],
) -> DualOutputResult:
    uart = {frame.sequence: frame for frame in uart_frames
            if frame.message_type in _SENSOR_TYPES}
    cdc = {frame.sequence: frame for frame in cdc_frames
           if frame.message_type in _SENSOR_TYPES}
    common = sorted(uart.keys() & cdc.keys())
    mismatches = tuple(
        sequence for sequence in common
        if _fingerprint(uart[sequence]) != _fingerprint(cdc[sequence])
    )
    return DualOutputResult(
        uart_sensor_frames=len(uart),
        cdc_sensor_frames=len(cdc),
        matched_frames=len(common) - len(mismatches),
        uart_only_sequences=tuple(sorted(uart.keys() - cdc.keys())),
        cdc_only_sequences=tuple(sorted(cdc.keys() - uart.keys())),
        content_mismatches=mismatches,
    )
