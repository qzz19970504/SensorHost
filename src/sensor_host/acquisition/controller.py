"""Qt-free transport, protocol, storage, and control orchestration."""

from __future__ import annotations

import queue
from threading import Event, Lock

from sensor_host.acquisition.models import AcquisitionHealth
from sensor_host.acquisition.sample_store import RealtimeSampleStore
from sensor_host.protocol import Frame, MessageType, StreamParser
from sensor_host.storage import RawSessionRecorder
from sensor_host.transport import Transport


_READ_CHUNK_BYTES = 65_536
_READ_TIMEOUT_SECONDS = 0.05
_MAXIMUM_COMMAND_BYTES = 94


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
        self._parser = StreamParser()
        self._commands: queue.Queue[bytes] = queue.Queue()
        self._cli_responses: queue.Queue[str] = queue.Queue()
        self._bytes_received = 0
        self._frames_received = 0
        self._last_error: str | None = None

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
        self.enqueue_command("acq start")

    def stop_acquisition(self) -> None:
        """Queue the firmware acquisition-stop command."""
        self.enqueue_command("acq stop")

    def set_watermark(self, words: int) -> None:
        """Queue one of the watermark values implemented by the firmware."""
        if words not in (128, 256, 511):
            raise ValueError("watermark must be 128, 256 or 511")
        self.enqueue_command(f"acq watermark {words}")

    def request_status(self) -> None:
        """Queue a firmware status request."""
        self.enqueue_command("status")

    def set_recorder(self, recorder: RawSessionRecorder | None) -> None:
        """Attach or detach an already-started recorder at a chunk boundary."""
        with self._recorder_lock:
            self._recorder = recorder

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
                with self._recorder_lock:
                    if self._recorder is not None:
                        self._recorder.submit(chunk)
                frames = self._parser.feed(chunk)
                self._frames_received += len(frames)
                for frame in frames:
                    self._handle_frame(frame)
                self._store.update_parser_stats(self._parser.stats)
        finally:
            self._transport.close()
            with self._recorder_lock:
                recorder = self._recorder
                self._recorder = None
            if recorder is not None:
                recorder.stop()

    def _send_pending_commands(self) -> None:
        while True:
            try:
                command = self._commands.get_nowait()
            except queue.Empty:
                return
            self._transport.write_control(command)

    def _handle_frame(self, frame: Frame) -> None:
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
            self._cli_responses.put_nowait(frame.cli_text)
