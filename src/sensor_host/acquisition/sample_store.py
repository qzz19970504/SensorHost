"""Thread-safe bounded storage for real-time sensor display snapshots."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, replace
from threading import Lock

import numpy as np
from numpy.typing import NDArray

from sensor_host.acquisition.models import UiSnapshot
from sensor_host.protocol import (
    FirmwareControlState,
    IisSample,
    Jy61plSample,
    ParserStats,
    StatusV1,
)


_DEFAULT_RETENTION_SECONDS = 30.0
_MICROSECONDS_PER_SECOND = 1_000_000.0
_MINIMUM_POINT_BUDGET = 2


@dataclass(frozen=True)
class _SampleChunk:
    timestamps_us: NDArray[np.float64]
    acceleration_g: NDArray[np.float64]


def envelope_indices(
    acceleration_g: NDArray[np.float64], max_points: int
) -> NDArray[np.int64]:
    """Select a bounded set of ordered indices while retaining strong peaks."""
    sample_count = acceleration_g.shape[0]
    if sample_count <= max_points:
        return np.arange(sample_count, dtype=np.int64)

    interior_budget = max_points - _MINIMUM_POINT_BUDGET
    if interior_budget == 0:
        return np.asarray((0, sample_count - 1), dtype=np.int64)
    bucket_count = max(1, (interior_budget + 1) // 2)
    bucket_edges = np.linspace(
        1,
        sample_count - 1,
        bucket_count + 1,
        dtype=np.int64,
    )
    magnitude = np.max(np.abs(acceleration_g), axis=1)
    selected_indices = {0, sample_count - 1}
    for bucket_start, bucket_stop in zip(bucket_edges[:-1], bucket_edges[1:]):
        if bucket_stop <= bucket_start:
            continue
        bucket_magnitude = magnitude[bucket_start:bucket_stop]
        selected_indices.add(
            bucket_start + int(np.argmin(bucket_magnitude))
        )
        selected_indices.add(
            bucket_start + int(np.argmax(bucket_magnitude))
        )

    endpoint_indices = {0, sample_count - 1}
    interior_candidates = selected_indices - endpoint_indices
    strongest_interior = sorted(
        interior_candidates,
        key=lambda sample_index: magnitude[sample_index],
        reverse=True,
    )[:interior_budget]
    ordered_indices = sorted(endpoint_indices.union(strongest_interior))
    return np.asarray(ordered_indices, dtype=np.int64)


class RealtimeSampleStore:
    """Own recent sensor samples and expose copied, display-sized snapshots."""

    def __init__(self, retention_s: float = _DEFAULT_RETENTION_SECONDS) -> None:
        if retention_s <= 0.0:
            raise ValueError("retention_s must be positive")
        self._retention_us = retention_s * _MICROSECONDS_PER_SECOND
        self._chunks: deque[_SampleChunk] = deque()
        self._latest_orientation: Jy61plSample | None = None
        self._orientation_received_s: float | None = None
        self._firmware_status: StatusV1 | None = None
        self._firmware_control_state: FirmwareControlState | None = None
        self._parser_stats = ParserStats()
        self._lock = Lock()

    def append_iis(self, samples: tuple[IisSample, ...]) -> None:
        """Append one decoded IIS batch and discard data beyond retention."""
        if not samples:
            return
        timestamps_us = np.fromiter(
            (sample.timestamp_us for sample in samples),
            dtype=np.float64,
            count=len(samples),
        )
        acceleration_g = np.asarray(
            [sample.acceleration_g for sample in samples],
            dtype=np.float64,
        )
        chunk = _SampleChunk(timestamps_us, acceleration_g)
        with self._lock:
            self._chunks.append(chunk)
            self._prune_locked(timestamps_us[-1])

    def update_jy(
        self,
        sample: Jy61plSample,
        received_monotonic_s: float | None = None,
    ) -> None:
        """Replace the latest orientation sample and its host receive time."""
        received_time_s = (
            time.monotonic()
            if received_monotonic_s is None
            else received_monotonic_s
        )
        with self._lock:
            self._latest_orientation = sample
            self._orientation_received_s = received_time_s

    def update_status(self, status: StatusV1) -> None:
        """Replace the latest immutable firmware status payload."""
        with self._lock:
            self._firmware_status = status

    def update_control_state(self, state: FirmwareControlState) -> None:
        """Replace the latest structured text control-state snapshot."""
        with self._lock:
            self._firmware_control_state = state

    def update_parser_stats(self, stats: ParserStats) -> None:
        """Copy parser counters so callers cannot mutate stored health state."""
        with self._lock:
            self._parser_stats = replace(stats)

    def snapshot(
        self,
        window_s: float,
        max_points: int,
        now_monotonic_s: float | None = None,
    ) -> UiSnapshot:
        """Return an immutable recent window bounded by a display point budget."""
        if window_s <= 0.0:
            raise ValueError("window_s must be positive")
        if max_points < _MINIMUM_POINT_BUDGET:
            raise ValueError("max_points must be at least 2")
        current_time_s = (
            time.monotonic()
            if now_monotonic_s is None
            else now_monotonic_s
        )

        with self._lock:
            timestamps_us, acceleration_g = self._window_arrays_locked(window_s)
            orientation = self._latest_orientation
            orientation_received_s = self._orientation_received_s
            firmware_status = self._firmware_status
            firmware_control_state = self._firmware_control_state
            parser_stats = replace(self._parser_stats)

        if timestamps_us.size:
            selected_indices = envelope_indices(acceleration_g, max_points)
            selected_timestamps_us = timestamps_us[selected_indices]
            selected_acceleration_g = acceleration_g[selected_indices]
            relative_time_s = (
                selected_timestamps_us - timestamps_us[-1]
            ) / _MICROSECONDS_PER_SECOND
            sample_rate_hz = self._estimate_sample_rate(timestamps_us)
        else:
            relative_time_s = np.empty(0, dtype=np.float64)
            selected_acceleration_g = np.empty((0, 3), dtype=np.float64)
            sample_rate_hz = 0.0

        orientation_age_s = None
        if orientation_received_s is not None:
            orientation_age_s = max(0.0, current_time_s - orientation_received_s)

        return UiSnapshot(
            time_s=self._readonly(relative_time_s),
            x_g=self._readonly(selected_acceleration_g[:, 0]),
            y_g=self._readonly(selected_acceleration_g[:, 1]),
            z_g=self._readonly(selected_acceleration_g[:, 2]),
            orientation=orientation,
            orientation_age_s=orientation_age_s,
            firmware_status=firmware_status,
            parser_stats=parser_stats,
            sample_rate_hz=sample_rate_hz,
            firmware_control_state=firmware_control_state,
        )

    def _prune_locked(self, latest_timestamp_us: float) -> None:
        cutoff_us = latest_timestamp_us - self._retention_us
        while self._chunks and self._chunks[0].timestamps_us[-1] < cutoff_us:
            self._chunks.popleft()
        if not self._chunks:
            return
        first_chunk = self._chunks[0]
        first_valid_index = int(
            np.searchsorted(first_chunk.timestamps_us, cutoff_us, side="left")
        )
        if first_valid_index == 0:
            return
        self._chunks[0] = _SampleChunk(
            first_chunk.timestamps_us[first_valid_index:].copy(),
            first_chunk.acceleration_g[first_valid_index:].copy(),
        )

    def _window_arrays_locked(
        self, window_s: float
    ) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        if not self._chunks:
            return (
                np.empty(0, dtype=np.float64),
                np.empty((0, 3), dtype=np.float64),
            )
        latest_timestamp_us = self._chunks[-1].timestamps_us[-1]
        cutoff_us = latest_timestamp_us - window_s * _MICROSECONDS_PER_SECOND
        timestamp_parts: list[NDArray[np.float64]] = []
        acceleration_parts: list[NDArray[np.float64]] = []
        for chunk in self._chunks:
            if chunk.timestamps_us[-1] < cutoff_us:
                continue
            first_valid_index = int(
                np.searchsorted(chunk.timestamps_us, cutoff_us, side="left")
            )
            timestamp_parts.append(chunk.timestamps_us[first_valid_index:])
            acceleration_parts.append(chunk.acceleration_g[first_valid_index:])
        return (
            np.concatenate(timestamp_parts).copy(),
            np.concatenate(acceleration_parts).copy(),
        )

    @staticmethod
    def _estimate_sample_rate(timestamps_us: NDArray[np.float64]) -> float:
        if timestamps_us.size < _MINIMUM_POINT_BUDGET:
            return 0.0
        duration_s = (
            timestamps_us[-1] - timestamps_us[0]
        ) / _MICROSECONDS_PER_SECOND
        if duration_s <= 0.0:
            return 0.0
        return float((timestamps_us.size - 1) / duration_s)

    @staticmethod
    def _readonly(values: NDArray[np.float64]) -> NDArray[np.float64]:
        copied_values = np.asarray(values, dtype=np.float64).copy()
        copied_values.setflags(write=False)
        return copied_values
