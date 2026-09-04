"""Qt-free transport, protocol, storage, and control orchestration."""

from __future__ import annotations

import queue
from threading import Event, Lock
from typing import Protocol
from uuid import UUID

from sensor_host.acquisition.models import AcquisitionHealth
from sensor_host.acquisition.sample_store import RealtimeSampleStore
from sensor_host.protocol import (
    ControlStateParseError,
    FirmwareControlState,
    Frame,
    MessageType,
    StreamParser,
)
from sensor_host.storage import RawSessionRecorder
from sensor_host.transport import Transport


_READ_CHUNK_BYTES = 65_536
_READ_TIMEOUT_SECONDS = 0.05
_MAXIMUM_COMMAND_BYTES = 94
_DEFERRED_RECORDING_CAPACITY_BYTES = 4 * 1024 * 1024


class DeviceIdentityError(RuntimeError):
    """Report multiple device UUIDs observed on one physical connection."""


class ArchiveRecorder(Protocol):
    """Accept complete archive-export frames without owning their lifecycle."""

    def submit(self, chunk: bytes) -> bool:
        """Queue one complete raw frame and report whether it was accepted."""


class AcquisitionController:
    """Run one connected acquisition session without depending on Qt."""

    def __init__(
        self,
        transport: Transport,
        store: RealtimeSampleStore,
        recorder: RawSessionRecorder | None = None,
    ) -> None:
        self._transport = transport
        self._store = store
        self._recorder = recorder
        self._recorder_lock = Lock()
        self._defer_recording = False
        self._deferred_recording_frames: list[bytes] = []
        self._deferred_recording_bytes = 0
        self._parser = StreamParser()
        self._commands: queue.Queue[bytes] = queue.Queue()
        self._cli_responses: queue.Queue[str] = queue.Queue()
        self._bytes_received = 0
        self._frames_received = 0
        self._last_error: str | None = None
        self._control_state = FirmwareControlState()
        self._identity_updates: queue.Queue[UUID] = queue.Queue()
        self._device_uuid: UUID | None = None
        self._archive_recorder: ArchiveRecorder | None = None
        self._archive_recorder_lock = Lock()

    @property
    def health(self) -> AcquisitionHealth:
        """Return an immutable host-side health snapshot."""
        recording_failure = None
        with self._recorder_lock:
            if self._recorder is not None:
                recording_failure = self._recorder.failure
        return AcquisitionHealth(
            bytes_received=self._bytes_received,
            frames_received=self._frames_received,
            recording_failure=recording_failure,
            last_error=self._last_error,
        )

    def enqueue_command(self, command: str) -> None:
        """Validate and enqueue one ASCII command without its line ending."""
        try:
            encoded_command = command.strip().encode("ascii", errors="strict")
        except UnicodeEncodeError as error:
            raise ValueError("command must contain ASCII characters") from error
        if (
            not encoded_command
            or len(encoded_command) > _MAXIMUM_COMMAND_BYTES
            or b"\x00" in encoded_command
        ):
            raise ValueError("command must contain 1..94 ASCII bytes without NUL")
        self._commands.put_nowait(encoded_command)

    def start_acquisition(self) -> None:
        """Queue the firmware acquisition-start command."""
        self.enqueue_command("AT+START")

    def stop_acquisition(self) -> None:
        """Queue the firmware acquisition-stop command."""
        self.enqueue_command("AT+STOP")

    def set_watermark(self, words: int) -> None:
        """Queue one of the watermark values implemented by the firmware."""
        if words not in (128, 256, 511):
            raise ValueError("watermark must be 128, 256 or 511")
        self.enqueue_command(f"acq watermark {words}")

    def request_status(self) -> None:
        """Queue a firmware status request."""
        self.enqueue_command("AT+STATE?")

    def request_uuid(self) -> None:
        """Queue a UUID and provenance query."""
        self.enqueue_command("AT+UUID?")

    def set_uuid(self, value: str) -> None:
        """Queue a canonical UUID update; firmware enforces IDLE state."""
        self.enqueue_command(f"AT+UUID={value}")

    def request_livestream(self) -> None:
        """Queue a query for the current live-stream target."""
        self.enqueue_command("AT+LIVESTREAM?")

    def set_livestream(self, target: str) -> None:
        """Set live-stream target to UART or CDC (IDLE only)."""
        normalized = target.upper()
        if normalized not in {"UART", "CDC"}:
            raise ValueError("live target must be UART or CDC")
        self.enqueue_command(f"AT+LIVESTREAM={normalized}")

    def export_archive(self, target: str = "UART") -> None:
        """Start explicit archive export on UART or CDC."""
        normalized = target.upper()
        if normalized not in {"UART", "CDC"}:
            raise ValueError("export target must be UART or CDC")
        self.enqueue_command(f"AT+EXPORT={normalized}")

    def set_recorder(self, recorder: RawSessionRecorder | None) -> None:
        """Attach or detach an already-started recorder at a chunk boundary."""
        with self._recorder_lock:
            self._recorder = recorder
            if recorder is not None:
                for frame_bytes in self._deferred_recording_frames:
                    if not recorder.submit(frame_bytes):
                        self._last_error = recorder.failure
                        break
            self._defer_recording = False
            self._deferred_recording_frames.clear()
            self._deferred_recording_bytes = 0

    def defer_recording_until_identity(self) -> None:
        """Buffer initial complete frames until a UUID-specific recorder exists."""
        with self._recorder_lock:
            if self._recorder is None:
                self._defer_recording = True

    def cancel_deferred_recording(self) -> None:
        """Discard initial frames if recording stops before identification."""
        with self._recorder_lock:
            self._defer_recording = False
            self._deferred_recording_frames.clear()
            self._deferred_recording_bytes = 0

    def set_archive_recorder(self, recorder: ArchiveRecorder | None) -> None:
        """Attach or detach a sink for complete ARCHIVE_EXPORT frames."""
        with self._archive_recorder_lock:
            self._archive_recorder = recorder

    def drain_identity_updates(self) -> list[UUID]:
        """Return newly established connection identities without blocking."""
        identities: list[UUID] = []
        while True:
            try:
                identities.append(self._identity_updates.get_nowait())
            except queue.Empty:
                return identities

    def drain_cli_responses(self) -> list[str]:
        """Return pending decoded CLI response frames without blocking."""
        responses: list[str] = []
        while True:
            try:
                responses.append(self._cli_responses.get_nowait())
            except queue.Empty:
                return responses

    def run(self, stop_event: Event, idle_limit: int | None = None) -> None:
        """Read until stopped, or until a test-only finite idle limit is met."""
        if idle_limit is not None and idle_limit <= 0:
            raise ValueError("idle_limit must be positive when provided")
        empty_read_count = 0
        try:
            while not stop_event.is_set():
                self._send_pending_commands()
                chunk = self._transport.read(
                    max_bytes=_READ_CHUNK_BYTES,
                    timeout_s=_READ_TIMEOUT_SECONDS,
                )
                if not chunk:
                    empty_read_count += 1
                    if idle_limit is not None and empty_read_count >= idle_limit:
                        break
                    continue

                empty_read_count = 0
                self._bytes_received += len(chunk)
                frames = self._parser.feed(chunk)
                self._frames_received += len(frames)
                for frame in frames:
                    self._handle_frame(frame)
                self._store.update_parser_stats(self._parser.stats)
        finally:
            self._transport.close()

    def _send_pending_commands(self) -> None:
        while True:
            try:
                command = self._commands.get_nowait()
            except queue.Empty:
                return
            self._transport.write_control(command)

    def _handle_frame(self, frame: Frame) -> None:
        if frame.device_uuid is not None:
            self._observe_identity(frame.device_uuid)
        if frame.archive_export:
            with self._archive_recorder_lock:
                archive_recorder = self._archive_recorder
                if archive_recorder is not None and not archive_recorder.submit(
                    frame.raw_bytes
                ):
                    self._last_error = "archive recording queue capacity exceeded"
            return
        with self._recorder_lock:
            recorder = self._recorder
            if recorder is not None:
                if not recorder.submit(frame.raw_bytes):
                    self._last_error = recorder.failure
            elif self._defer_recording:
                next_size = self._deferred_recording_bytes + len(frame.raw_bytes)
                if next_size <= _DEFERRED_RECORDING_CAPACITY_BYTES:
                    self._deferred_recording_frames.append(frame.raw_bytes)
                    self._deferred_recording_bytes = next_size
                else:
                    self._last_error = "deferred recording capacity exceeded"
        if frame.message_type is MessageType.IIS3DWB_FIFO:
            self._store.append_iis(frame.iis_samples or ())
            return
        if frame.message_type is MessageType.JY61PL_SAMPLE:
            if frame.jy61pl is not None:
                self._store.update_jy(frame.jy61pl)
            return
        if frame.message_type is MessageType.STATUS and frame.status is not None:
            self._store.update_status(frame.status)
            return
        if frame.message_type is MessageType.CLI_RESPONSE and frame.cli_text is not None:
            try:
                self._control_state = self._control_state.updated_from_cli(frame.cli_text)
            except ControlStateParseError as error:
                self._last_error = str(error)
            else:
                self._store.update_control_state(self._control_state)
                if self._control_state.device_uuid is not None:
                    self._observe_identity(self._control_state.device_uuid)
            self._cli_responses.put_nowait(frame.cli_text)

    def _observe_identity(self, device_uuid: UUID) -> None:
        if self._device_uuid is None:
            self._device_uuid = device_uuid
            self._identity_updates.put_nowait(device_uuid)
            return
        if self._device_uuid != device_uuid:
            raise DeviceIdentityError(
                f"connection changed UUID from {self._device_uuid} to {device_uuid}"
            )
