"""Immutable CDC acceptance result and strict pass criteria."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass


@dataclass(frozen=True)
class AcceptanceReport:
    duration_s: float
    bytes_received: int
    frames: int
    crc_errors: int
    sequence_gaps: int
    source_drop_delta: int
    transport_drop_delta: int
    fifo_overrun_delta: int
    recorder_bytes: int
    replay_frames: int
    jy61pl_frames: int = 0
    replay_crc_errors: int = 0
    replay_sequence_gaps: int = 0

    @property
    def passed(self) -> bool:
        """Require non-empty, replayable data with zero integrity failures."""
        return (
            self.duration_s > 0.0
            and self.bytes_received > 0
            and self.frames > 0
            and self.crc_errors == 0
            and self.sequence_gaps == 0
            and self.source_drop_delta == 0
            and self.transport_drop_delta == 0
            and self.fifo_overrun_delta == 0
            and self.recorder_bytes == self.bytes_received
            and self.replay_frames == self.frames
            and self.replay_crc_errors == 0
            and self.replay_sequence_gaps == 0
        )

    def with_updates(self, **changes: object) -> "AcceptanceReport":
        """Return a copy with selected fields replaced for tests and analysis."""
        return dataclasses.replace(self, **changes)
