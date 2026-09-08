"""Immutable acquisition models shared with the presentation layer."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
from numpy.typing import NDArray

from sensor_host.protocol import FirmwareControlState, Jy61plSample, ParserStats, StatusV1


@dataclass(frozen=True)
class UiSnapshot:
    """Describe one immutable, display-bounded view of acquisition state."""

    time_s: NDArray[np.float64]
    x_g: NDArray[np.float64]
    y_g: NDArray[np.float64]
    z_g: NDArray[np.float64]
    orientation: Jy61plSample | None
    orientation_age_s: float | None
    firmware_status: StatusV1 | None
    parser_stats: ParserStats
    sample_rate_hz: float
    firmware_control_state: FirmwareControlState | None = None


@dataclass(frozen=True)
class AcquisitionHealth:
    """Summarize host-side ingest and recording health."""

    bytes_received: int = 0
    frames_received: int = 0
    recording_failure: str | None = None
    last_error: str | None = None


class ConnectionState(str, Enum):
    """Represent the externally visible acquisition lifecycle."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    STREAMING = "streaming"
    RECONNECTING = "reconnecting"
    STOPPING = "stopping"
    OFFLINE = "offline"
