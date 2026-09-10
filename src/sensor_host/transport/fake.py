"""Deterministic virtual transport used to exercise the host UI without hardware."""

from __future__ import annotations

import math
import struct
import time
import uuid
import zlib
from collections import deque
from collections.abc import Callable

from sensor_host.protocol.sdf1 import (
    DATA_HEADER_SIZE,
    HEADER_SIZE,
    MessageType,
)
from sensor_host.transport.base import DeviceDescriptor, TransportError


_HEADER = struct.Struct("<4sBBHHHIQHH")
_CRC_SIZE = 4
_ARCHIVE_FLAG = 0x8000
_MAXIMUM_CONTROL_BYTES = 94
_LIVE_INTERVAL_SECONDS = 0.05
_EXPORT_INTERVAL_SECONDS = 0.12
_TIMESTAMP_START_US = 1_700_000_000_000_000
_JY_SAMPLE_PERIOD_US = 37_500
_IIS_TIMESTAMP_TICK_US = 25
_IIS_WORD_SIZE = 7
_SD_CAPACITY_BYTES = 16_384
_SD_FRAME_COUNT = 24
_SD_FRAME_BYTES = 62


class FakeTransport:
    """Simulate one sensor while preserving the production transport contract.

    Frames are generated when :meth:`read` is called, rather than from a
    producer thread.  This keeps the fake bounded and makes it safe to stop
    immediately when the host sends ``AT+STOP``.
    """

    DEVICE_ID = "FAKE-001"
    DEVICE_UUID = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock or time.monotonic
        self._opened = False
        self._state = "IDLE"
        self._live_target = "UART"
        self._export_target = "NONE"
        self._export_active = False
        self._export_frame_index = 0
        self._next_live_at = 0.0
        self._next_export_at = 0.0
        self._sensor_sequence = 0
        self._cli_sequence = 0
        self._sensor_frame_index = 0
        self._pending_packets: deque[bytes] = deque()
        self._pending_bytes = b""
        self._sd_used = _SD_FRAME_COUNT * _SD_FRAME_BYTES
        self._sd_retained_frames = _SD_FRAME_COUNT
        self._sd_retained_chunks = 1
        self._sd_overwritten_frames = 0

    def discover(self) -> list[DeviceDescriptor]:
        """Return the single virtual endpoint exposed by fake mode."""
        return [
            DeviceDescriptor(
                device_id=self.DEVICE_ID,
                label="FAKE-001 — Simulated Sensor",
            )
        ]

    def open(self, device_id: str) -> None:
        """Open the virtual endpoint and reset its deterministic session clock."""
        if device_id != self.DEVICE_ID:
            raise TransportError(f"unknown fake device {device_id}")
        if self._opened:
            raise TransportError("a fake endpoint is already open")
        self._opened = True
        self._next_live_at = self._clock()

    def close(self) -> None:
        """Close the virtual endpoint; repeated close is harmless."""
        self._opened = False
        self._pending_packets.clear()
        self._pending_bytes = b""
        self._export_active = False
        self._export_target = "NONE"
        self._state = "IDLE"

    def read(self, max_bytes: int, timeout_s: float) -> bytes:
        """Return one scheduled SDF1 packet before the bounded timeout expires."""
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if timeout_s < 0.0:
            raise ValueError("timeout_s must not be negative")
        self._require_open()

        deadline = self._clock() + timeout_s
        while True:
            packet = self._take_pending_packet()
            if packet is not None:
                return self._take_bytes(packet, max_bytes)

            now = self._clock()
            if self._export_active:
                if self._export_frame_index >= _SD_FRAME_COUNT:
                    self._finish_export()
                    continue
                if now >= self._next_export_at:
                    frame = self._make_jy_frame(
                        archive=True,
                        sequence=self._export_frame_index + 1,
                    )
                    self._export_frame_index += 1
                    self._next_export_at = now + _EXPORT_INTERVAL_SECONDS
                    return self._take_bytes(frame, max_bytes)
            elif now >= self._next_live_at:
                frame = self._make_live_frame()
                self._next_live_at = now + _LIVE_INTERVAL_SECONDS
                return self._take_bytes(frame, max_bytes)

            remaining = deadline - now
            if remaining <= 0.0:
                return b""
            next_due = self._next_export_at if self._export_active else self._next_live_at
            time.sleep(min(0.005, remaining, max(0.0, next_due - now)))

    def write_control(self, command: bytes) -> None:
        """Apply one host control command and queue a framed CLI response."""
        self._require_open()
        content = bytes(command).rstrip(b"\r\n")
        if not content or len(content) > _MAXIMUM_CONTROL_BYTES:
            raise ValueError("control command must contain 1..94 bytes")
        if b"\x00" in content or any(value > 0x7F for value in content):
            raise ValueError("control command must contain ASCII without NUL")
        text = content.decode("ascii").strip()
        normalized = text.upper()

        if normalized == "AT+UUID?":
            self._queue_cli(f"+UUID:{self.DEVICE_UUID},SOURCE=FAKE\r\nOK\r\n")
            return
        if normalized == "AT+STATE?":
            self._queue_cli(self._state_reply())
            return
        if normalized == "AT+LIVESTREAM?":
            self._queue_cli(f"+LIVESTREAM:{self._live_target}\r\nOK\r\n")
            return
        if normalized.startswith("AT+LIVESTREAM="):
            target = normalized.removeprefix("AT+LIVESTREAM=")
            if target not in {"UART", "CDC"} or self._state not in {"IDLE", "ERROR"}:
                self._queue_cli("ERROR:STATE\r\n")
                return
            self._live_target = target
            self._queue_cli("OK\r\n")
            return
        if normalized in {"AT+START", "AT+STOP"}:
            self._handle_acquisition_command(normalized)
            return
        if normalized.startswith("AT+EXPORT="):
            self._start_export(normalized.removeprefix("AT+EXPORT="))
            return
        if normalized == "AT+SDCLEAR=CONFIRM":
            self._clear_sd()
            return
        if normalized.startswith("ACQ WATERMARK "):
            self._queue_cli("OK\r\n")
            return
        self._queue_cli("ERROR:UNKNOWN\r\n")

    def _handle_acquisition_command(self, command: str) -> None:
        if command == "AT+START":
            if self._state not in {"IDLE", "ERROR"}:
                self._queue_cli("ERROR:STATE\r\n")
                return
            self._state = "ACQUIRE"
            self._queue_cli("+STATE:ACQUIRE\r\nOK\r\n")
            return

        if self._export_active:
            self._export_active = False
            self._export_target = "NONE"
            self._export_frame_index = 0
        if self._state in {"ACQUIRE", "EXPORT", "IDLE", "ERROR"}:
            self._state = "IDLE"
            self._queue_cli("OK\r\n")
            return
        self._queue_cli("ERROR:STATE\r\n")

    def _start_export(self, target: str) -> None:
        if target not in {"UART", "CDC"} or self._state not in {"IDLE", "ERROR"}:
            self._queue_cli("ERROR:STATE\r\n")
            return
        if self._sd_retained_frames == 0:
            self._queue_cli("EXPORT_EMPTY\r\n")
            return
        self._state = "EXPORT"
        self._export_target = target
        self._export_active = True
        self._export_frame_index = 0
        self._next_export_at = self._clock() + _EXPORT_INTERVAL_SECONDS
        self._queue_cli(f"EXPORT_BEGIN:{target}\r\nOK\r\n")

    def _clear_sd(self) -> None:
        if self._state not in {"IDLE", "ERROR"}:
            self._queue_cli("ERROR:STATE\r\n")
            return
        self._sd_used = 0
        self._sd_retained_frames = 0
        self._sd_retained_chunks = 0
        self._sd_overwritten_frames = 0
        self._queue_cli("OK\r\n")

    def _finish_export(self) -> None:
        self._export_active = False
        self._state = "IDLE"
        self._export_target = "NONE"
        self._sd_used = 0
        self._sd_retained_frames = 0
        self._sd_retained_chunks = 0
        self._queue_cli(
            "EXPORT_END:CHUNKS=1,FRAMES=24\r\n"
            + self._state_reply()
        )

    def _state_reply(self) -> str:
        return (
            f"+STATE:{self._state}\r\n"
            f"+SD:USED={self._sd_used},CAPACITY={_SD_CAPACITY_BYTES},"
            f"PENDING_FRAMES=0,RETAINED_CHUNKS={self._sd_retained_chunks},"
            f"RETAINED_FRAMES={self._sd_retained_frames},OVERWRITTEN_CHUNKS=0,"
            f"OVERWRITTEN_FRAMES={self._sd_overwritten_frames},READY=1,"
            "FORMAT_REQUIRED=0\r\n"
            f"+EXPORT:TARGET={self._export_target},CHUNK={self._export_frame_index},"
            f"FRAME={self._export_frame_index}\r\nOK\r\n"
        )

    def _make_live_frame(self) -> bytes:
        self._sensor_frame_index += 1
        if self._sensor_frame_index % 2:
            return self._make_iis_frame()
        return self._make_jy_frame(archive=False)

    def _make_iis_frame(self) -> bytes:
        frame_index = self._sensor_frame_index
        timestamp_us = _TIMESTAMP_START_US + frame_index * _JY_SAMPLE_PERIOD_US
        timestamp_ticks = (timestamp_us // _IIS_TIMESTAMP_TICK_US) & 0xFFFFFFFF
        payload = bytes([4 << 3]) + struct.pack("<I", timestamp_ticks) + b"\x00\x00"
        for sample_index in range(8):
            phase = frame_index * 0.18 + sample_index * 0.31
            raw = (
                int(6000 * math.sin(phase)),
                int(5000 * math.cos(phase * 0.8)),
                16_384 + int(300 * math.sin(phase * 0.4)),
            )
            payload += bytes([2 << 3]) + struct.pack("<hhh", *raw)
        self._sensor_sequence += 1
        return self._encode_data_frame(
            MessageType.IIS3DWB_FIFO,
            payload,
            item_count=9,
            sequence=self._sensor_sequence,
            timestamp_us=timestamp_us,
        )

    def _make_jy_frame(self, archive: bool, sequence: int | None = None) -> bytes:
        frame_index = self._sensor_frame_index + self._export_frame_index
        phase = frame_index * 0.14
        raw = (
            int(4_000 * math.sin(phase)),
            int(4_000 * math.cos(phase)),
            16_384,
            2_500,
            int(8_000 * math.sin(phase * 0.5)),
            int(6_000 * math.cos(phase * 0.6)),
            int(3_000 * math.sin(phase * 0.7)),
        )
        timestamp_us = _TIMESTAMP_START_US + max(frame_index, 1) * _JY_SAMPLE_PERIOD_US
        if sequence is None:
            self._sensor_sequence += 1
            sequence = self._sensor_sequence
        return self._encode_data_frame(
            MessageType.JY61PL_SAMPLE,
            struct.pack("<7h", *raw),
            item_count=1,
            sequence=sequence,
            timestamp_us=timestamp_us,
            flags=_ARCHIVE_FLAG if archive else 0,
        )

    def _encode_data_frame(
        self,
        message_type: MessageType,
        payload: bytes,
        *,
        item_count: int,
        sequence: int,
        timestamp_us: int,
        flags: int = 0,
    ) -> bytes:
        header = _HEADER.pack(
            b"SDF1",
            2,
            int(message_type),
            flags,
            DATA_HEADER_SIZE,
            len(payload),
            sequence,
            timestamp_us,
            item_count,
            0,
        )
        content = header + self.DEVICE_UUID.bytes + payload
        return content + struct.pack("<I", zlib.crc32(content) & 0xFFFFFFFF)

    def _queue_cli(self, text: str) -> None:
        payload = text.encode("utf-8")
        self._cli_sequence += 1
        header = _HEADER.pack(
            b"SDF1",
            1,
            int(MessageType.CLI_RESPONSE),
            0,
            HEADER_SIZE,
            len(payload),
            self._cli_sequence,
            _TIMESTAMP_START_US + self._cli_sequence,
            1,
            0,
        )
        content = header + payload
        self._pending_packets.append(
            content + struct.pack("<I", zlib.crc32(content) & 0xFFFFFFFF)
        )

    def _take_pending_packet(self) -> bytes | None:
        if self._pending_bytes:
            packet = self._pending_bytes
            self._pending_bytes = b""
            return packet
        if self._pending_packets:
            return self._pending_packets.popleft()
        return None

    def _take_bytes(self, packet: bytes, max_bytes: int) -> bytes:
        if len(packet) <= max_bytes:
            return packet
        self._pending_bytes = packet[max_bytes:]
        return packet[:max_bytes]

    def _require_open(self) -> None:
        if not self._opened:
            raise TransportError("fake endpoint is not open")
