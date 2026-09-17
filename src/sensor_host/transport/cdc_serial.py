"""USB CDC serial adapter for STM32 SDF1 acquisition."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, Protocol

import serial
from serial.tools import list_ports

from sensor_host.transport.base import DeviceDescriptor, TransportError


_CDC_BAUD_PLACEHOLDER = 115_200
_DEFAULT_TIMEOUT_SECONDS = 0.05
_MAXIMUM_CONTROL_BYTES = 94
_MAXIMUM_ASCII_BYTE = 0x7F


class _SerialPort(Protocol):
    timeout: float | None
    in_waiting: int

    def read(self, count: int) -> bytes:
        """Read at most count bytes."""

    def write(self, data: bytes) -> int:
        """Write bytes and return their accepted count."""

    def close(self) -> None:
        """Close the port."""


class CdcSerialTransport:
    """Discover and operate the STM32 USB virtual COM interface."""

    def __init__(
        self,
        serial_factory: Callable[..., _SerialPort] | None = None,
        port_enumerator: Callable[[], Iterable[Any]] | None = None,
    ) -> None:
        self._serial_factory = serial_factory or serial.Serial
        self._port_enumerator = port_enumerator or list_ports.comports
        self._serial_port: _SerialPort | None = None
        self._device_id: str | None = None

    def discover(self) -> list[DeviceDescriptor]:
        """Enumerate COM ports without opening or filtering user devices."""
        devices: list[DeviceDescriptor] = []
        for port in self._port_enumerator():
            device_id = str(port.device)
            description = str(port.description or "Serial Port")
            devices.append(
                DeviceDescriptor(
                    device_id=device_id,
                    label=f"{device_id} — {description}",
                    vid=port.vid,
                    pid=port.pid,
                )
            )
        return sorted(devices, key=lambda device: device.device_id)

    def open(self, device_id: str) -> None:
        """Open a CDC endpoint; baudrate is a conventional host setting only."""
        if not device_id:
            raise ValueError("device_id must not be empty")
        if self._serial_port is not None:
            raise TransportError("a CDC endpoint is already open")
        try:
            serial_port = self._serial_factory(
                port=device_id,
                baudrate=_CDC_BAUD_PLACEHOLDER,
                timeout=_DEFAULT_TIMEOUT_SECONDS,
            )
        except (serial.SerialException, OSError) as error:
            raise TransportError(f"cannot open CDC endpoint {device_id}: {error}") from error
        self._serial_port = serial_port
        self._device_id = device_id

    def close(self) -> None:
        """Close the current CDC endpoint; repeated close is harmless."""
        serial_port = self._serial_port
        device_id = self._device_id
        self._serial_port = None
        self._device_id = None
        if serial_port is None:
            return
        try:
            serial_port.close()
        except (serial.SerialException, OSError) as error:
            raise TransportError(f"cannot close CDC endpoint {device_id}: {error}") from error

    def read(self, max_bytes: int, timeout_s: float) -> bytes:
        """Read a bounded available chunk, waiting for one byte when idle."""
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if timeout_s < 0.0:
            raise ValueError("timeout_s must not be negative")
        serial_port = self._require_open_port()
        serial_port.timeout = timeout_s
        try:
            available_bytes = max(1, serial_port.in_waiting)
            return bytes(serial_port.read(min(max_bytes, available_bytes)))
        except (serial.SerialException, OSError) as error:
            raise TransportError(
                f"cannot read CDC endpoint {self._device_id}: {error}"
            ) from error

    def write_control(self, command: bytes) -> None:
        """Validate one ASCII command and transmit it with exactly one CRLF."""
        content = bytes(command).rstrip(b"\r\n")
        if not content or len(content) > _MAXIMUM_CONTROL_BYTES:
            raise ValueError("control command must contain 1..94 bytes")
        if b"\x00" in content or any(
            value > _MAXIMUM_ASCII_BYTE for value in content
        ):
            raise ValueError("control command must contain ASCII without NUL")
        serial_port = self._require_open_port()
        encoded_line = content + b"\r\n"
        try:
            bytes_written = serial_port.write(encoded_line)
        except (serial.SerialException, OSError) as error:
            raise TransportError(
                f"cannot write CDC endpoint {self._device_id}: {error}"
            ) from error
        if bytes_written != len(encoded_line):
            raise TransportError(
                f"short CDC control write on {self._device_id}: "
                f"{bytes_written}/{len(encoded_line)} bytes"
            )

    def write_raw(self, data: bytes) -> None:
        """Write raw bytes verbatim for a binary OTA frame (no ASCII framing)."""
        payload = bytes(data)
        if not payload:
            raise ValueError("raw write must contain at least one byte")
        serial_port = self._require_open_port()
        try:
            bytes_written = serial_port.write(payload)
        except (serial.SerialException, OSError) as error:
            raise TransportError(
                f"cannot write CDC endpoint {self._device_id}: {error}"
            ) from error
        if bytes_written != len(payload):
            raise TransportError(
                f"short CDC raw write on {self._device_id}: "
                f"{bytes_written}/{len(payload)} bytes"
            )

    def _require_open_port(self) -> _SerialPort:
        if self._serial_port is None:
            raise TransportError("CDC endpoint is not open")
        return self._serial_port
