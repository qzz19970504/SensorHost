"""Transport contracts for raw SDF1 bytes and line-oriented control."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class DeviceDescriptor:
    """Describe one user-selectable transport endpoint."""

    device_id: str
    label: str
    vid: int | None = None
    pid: int | None = None


class Transport(Protocol):
    """Define the raw-byte interface shared by CDC and future gateways."""

    def discover(self) -> list[DeviceDescriptor]:
        """Return currently selectable endpoints."""

    def open(self, device_id: str) -> None:
        """Open one endpoint for raw reads and control writes."""

    def close(self) -> None:
        """Release the endpoint and its operating-system handle."""

    def read(self, max_bytes: int, timeout_s: float) -> bytes:
        """Read up to max_bytes, returning empty bytes on timeout."""

    def write_control(self, command: bytes) -> None:
        """Write one control line after transport-specific normalization."""

    def write_raw(self, data: bytes) -> None:
        """Write raw bytes verbatim, e.g. a binary OTAF frame during OTA."""


class TransportError(RuntimeError):
    """Report an endpoint I/O failure with transport context."""
