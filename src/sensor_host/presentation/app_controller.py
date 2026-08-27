"""Qt lifecycle adapter around the Qt-free acquisition controller."""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from PyQt6.QtCore import QObject, QThread, QTimer, Qt, pyqtSignal, pyqtSlot

from sensor_host.acquisition import AcquisitionController, RealtimeSampleStore
from sensor_host.storage import RawSessionRecorder
from sensor_host.transport import Transport


_SNAPSHOT_INTERVAL_MS = 33
_STATUS_INTERVAL_MS = 5_000
_THREAD_STOP_TIMEOUT_MS = 3_000


class AcquisitionWorker(QObject):
    """Run blocking transport reads away from the GUI thread."""

    started = pyqtSignal()
    stopped = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, controller: AcquisitionController, stop_event: threading.Event) -> None:
        super().__init__()
        self._controller = controller
        self._stop_event = stop_event

    @pyqtSlot()
    def run(self) -> None:
        self.started.emit()
        try:
            self._controller.run(self._stop_event)
        except Exception as error:  # task boundary: report worker failure to the UI
            self.failed.emit(str(error))
        finally:
            self.stopped.emit()


class AppController(QObject):
    """Own exactly one acquisition worker, store and display timer."""

    snapshot_ready = pyqtSignal(object)
    health_ready = pyqtSignal(object)
    cli_response = pyqtSignal(str)
    connection_changed = pyqtSignal(bool, str)
    error_raised = pyqtSignal(str)

    def __init__(self, transport_factory: Callable[[], Transport]) -> None:
        super().__init__()
        self._transport_factory = transport_factory
        self._thread: QThread | None = None
        self._worker: AcquisitionWorker | None = None
        self._stop_event: threading.Event | None = None
        self._store: RealtimeSampleStore | None = None
        self._acquisition: AcquisitionController | None = None
        self._recorder: RawSessionRecorder | None = None
        self._window_s = 10.0
        self._display_paused = False
        self._timer = QTimer(self)
        self._timer.setInterval(_SNAPSHOT_INTERVAL_MS)
        self._timer.timeout.connect(self._publish_snapshot)
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(_STATUS_INTERVAL_MS)
        self._status_timer.timeout.connect(self._request_status)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    @pyqtSlot(str)
    def connect_device(self, device_id: str) -> None:
        if self.is_running:
            self.error_raised.emit("an acquisition session is already running")
            return
        transport = self._transport_factory()
        try:
            transport.open(device_id)
        except (OSError, RuntimeError, ValueError) as error:
            self.error_raised.emit(str(error))
            self.connection_changed.emit(False, device_id)
            return
        self._store = RealtimeSampleStore()
        self._acquisition = AcquisitionController(transport, self._store)
        self._acquisition.request_status()
        self._stop_event = threading.Event()
        self._thread = QThread(self)
        self._worker = AcquisitionWorker(self._acquisition, self._stop_event)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.stopped.connect(
            self._thread.quit,
            Qt.ConnectionType.DirectConnection,
        )
        self._worker.failed.connect(self._on_worker_failed)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()
        self._timer.start()
        self._status_timer.start()
        self.connection_changed.emit(True, device_id)

    @pyqtSlot()
    def disconnect_device(self) -> None:
        thread = self._thread
        stop_event = self._stop_event
        if thread is None:
            return
        self._timer.stop()
        self._status_timer.stop()
        if stop_event is not None:
            stop_event.set()
        thread.quit()
        if not thread.wait(_THREAD_STOP_TIMEOUT_MS):
            self.error_raised.emit("acquisition thread did not stop within three seconds")
            return
        self._clear_session()
        self.connection_changed.emit(False, "")

    @pyqtSlot(str)
    def send_command(self, command: str) -> None:
        if self._acquisition is None:
            self.error_raised.emit("connect to a CDC device before sending commands")
            return
        try:
            self._acquisition.enqueue_command(command)
        except ValueError as error:
            self.error_raised.emit(str(error))

    @pyqtSlot(int)
    def set_watermark(self, words: int) -> None:
        if self._acquisition is None:
            return
        try:
            self._acquisition.set_watermark(words)
        except ValueError as error:
            self.error_raised.emit(str(error))

    @pyqtSlot(bool)
    def set_display_paused(self, paused: bool) -> None:
        self._display_paused = paused

    @pyqtSlot(float)
    def set_window_seconds(self, window_s: float) -> None:
        if window_s > 0.0:
            self._window_s = window_s

    def set_recording(self, enabled: bool, path: Path | None = None) -> None:
        acquisition = self._acquisition
        if enabled:
            if acquisition is None:
                self.error_raised.emit("connect before starting a recording")
                return
            if self._recorder is not None:
                return
            output_path = path or self._default_recording_path()
            recorder = RawSessionRecorder()
            try:
                recorder.start(output_path, {"transport": "cdc", "format": "SDF1"})
            except OSError as error:
                self.error_raised.emit(str(error))
                return
            self._recorder = recorder
            acquisition.set_recorder(recorder)
            return
        if self._recorder is None or acquisition is None:
            return
        recorder = self._recorder
        acquisition.set_recorder(None)
        self._recorder = None
        try:
            recorder.stop()
        except RuntimeError as error:
            self.error_raised.emit(str(error))

    @pyqtSlot()
    def _publish_snapshot(self) -> None:
        acquisition = self._acquisition
        store = self._store
        if acquisition is None or store is None:
            return
        for response in acquisition.drain_cli_responses():
            self.cli_response.emit(response)
        self.health_ready.emit(acquisition.health)
        if not self._display_paused:
            self.snapshot_ready.emit(store.snapshot(self._window_s, max_points=5_000))

    @pyqtSlot()
    def _request_status(self) -> None:
        if self._acquisition is not None:
            self._acquisition.request_status()

    @pyqtSlot(str)
    def _on_worker_failed(self, message: str) -> None:
        self.error_raised.emit(message)

    @pyqtSlot()
    def _on_thread_finished(self) -> None:
        self._timer.stop()
        self._status_timer.stop()

    def _clear_session(self) -> None:
        thread = self._thread
        worker = self._worker
        if worker is not None:
            worker.deleteLater()
        if thread is not None:
            thread.deleteLater()
        self._thread = None
        self._worker = None
        self._stop_event = None
        self._store = None
        self._acquisition = None
        self._recorder = None

    @staticmethod
    def _default_recording_path() -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return Path("host") / "recordings" / f"session-{stamp}.sdf1"
