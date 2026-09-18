"""Qt lifecycle and multi-node coordination for host acquisition sessions."""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from PyQt6.QtCore import QObject, QSettings, QThread, QTimer, Qt, pyqtSignal, pyqtSlot

from sensor_host.acquisition import (
    AcquisitionController,
    ConnectionState,
    DuplicateDeviceError,
    NodeSessionManager,
    NodeSummary,
    RealtimeSampleStore,
    TransportKind,
)
from sensor_host.ota import (
    TARGET_ID,
    OtaPackage,
    OtaPackageError,
    OtaUploadCancelled,
    OtaUploadError,
    OtaUploader,
    describe_nack,
    format_crc,
    load_package,
)
from sensor_host.storage import RawSessionRecorder
from sensor_host.storage.paths import data_root
from sensor_host.transport import (
    AcceptedGatewayClient,
    GatewayListener,
    Transport,
    UdpWakeService,
    WifiServerConfig,
)


_SNAPSHOT_INTERVAL_MS = 33
_STATUS_INTERVAL_MS = 5_000
_THREAD_STOP_TIMEOUT_MS = 3_000
_MAXIMUM_WIFI_SESSIONS = 16
_MAXIMUM_DISPLAY_POINTS = 5_000
_IIS_SAMPLE_RATE_HZ = 26_667.0
_EXPORT_FIRST_BYTE_TIMEOUT_S = 10.0
_EXPORT_AUTO_RETRIES = 1
_OTA_RECONNECT_POLL_MS = 1_000
_OTA_RECONNECT_TIMEOUT_S = 60.0
_OTA_ACK_TIMEOUT_S = 2.0
_OTA_COMMIT_TIMEOUT_S = 30.0
_SAFE_PATH_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


class AcquisitionWorker(QObject):
    """Run one blocking transport reader outside the GUI thread."""

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
        except Exception as error:  # task boundary: unexpected failures must reach the UI
            self.failed.emit(str(error))
        finally:
            self.stopped.emit()


class GatewayAcceptWorker(QObject):
    """Wait for gateway clients without blocking the GUI event loop."""

    client_accepted = pyqtSignal(object)
    failed = pyqtSignal(str)
    stopped = pyqtSignal()

    def __init__(self, listener: GatewayListener, stop_event: threading.Event) -> None:
        super().__init__()
        self._listener = listener
        self._stop_event = stop_event

    @pyqtSlot()
    def run(self) -> None:
        try:
            while not self._stop_event.is_set():
                client = self._listener.accept(0.2)
                if client is not None:
                    self.client_accepted.emit((self._listener, client))
                else:
                    self._stop_event.wait(0.01)
        except (OSError, RuntimeError) as error:
            if not self._stop_event.is_set():
                self.failed.emit(str(error))
        finally:
            self.stopped.emit()


class _ControllerOtaAdapter:
    """Bridge the OtaUploader transport contract to one AcquisitionController."""

    def __init__(self, acquisition: AcquisitionController) -> None:
        self._acquisition = acquisition

    def send(self, data: bytes) -> None:
        self._acquisition.send_ota_frame(data)

    def readline(self, timeout: float) -> bytes | None:
        return self._acquisition.next_ota_reply(timeout)


class OtaUploadWorker(QObject):
    """Drive one OTA upload off the GUI thread over a session's OTA bridge."""

    progress = pyqtSignal(str, int, int, str)
    staged = pyqtSignal(str, object)
    failed = pyqtSignal(str, str, str)
    cancelled = pyqtSignal(str)
    stopped = pyqtSignal()

    def __init__(
        self,
        node_id: str,
        acquisition: AcquisitionController,
        package: bytes,
        cancel_event: threading.Event,
    ) -> None:
        super().__init__()
        self._node_id = node_id
        self._acquisition = acquisition
        self._package = package
        self._cancel_event = cancel_event

    @pyqtSlot()
    def run(self) -> None:
        adapter = _ControllerOtaAdapter(self._acquisition)
        uploader = OtaUploader(
            ack_timeout=_OTA_ACK_TIMEOUT_S,
            commit_timeout=_OTA_COMMIT_TIMEOUT_S,
            cancel_requested=self._cancel_event.is_set,
        )
        try:
            result = uploader.upload(
                package=self._package,
                transport=adapter,
                expected_target_id=TARGET_ID,
                progress=lambda sent, total, phase: self.progress.emit(
                    self._node_id, sent, total, phase
                ),
            )
        except OtaUploadCancelled:
            self.cancelled.emit(self._node_id)
        except OtaUploadError as error:
            self.failed.emit(self._node_id, error.code or "", str(error))
        except Exception as error:  # task boundary: unexpected failures reach the UI
            self.failed.emit(self._node_id, "", str(error))
        else:
            self.staged.emit(self._node_id, result)
        finally:
            self.stopped.emit()


@dataclass
class _ManagedSession:
    node_id: str
    peer: str
    transport_kind: TransportKind
    transport: Transport
    store: RealtimeSampleStore
    acquisition: AcquisitionController
    stop_event: threading.Event
    thread: QThread
    worker: AcquisitionWorker
    recorder: RawSessionRecorder | None = None
    archive_recorder: RawSessionRecorder | None = None
    archive_start_revision: int = 0
    archive_total_bytes: int = 0
    archive_path: Path | None = None
    archive_started_s: float = 0.0
    archive_target: str = ""
    archive_retries: int = 0
    archive_cancel_requested: bool = False
    failure: str | None = None
    ota_active: bool = False
    ota_awaiting_restart: bool = False


@dataclass(frozen=True)
class SdRecordInfo:
    """Describe one device's virtual SD ring record for the archive view."""

    node_id: str
    alias: str
    uuid_suffix: str
    transport: str
    sd_ready: bool | None
    sd_format_required: bool | None
    used_bytes: int | None
    capacity_bytes: int | None
    retained_frames: int | None
    retained_chunks: int | None
    overwritten_frames: int | None
    estimated_duration_s: float | None
    export_phase: str | None


class AppController(QObject):
    """Coordinate one CDC session or up to sixteen independent Wi-Fi sessions."""

    snapshot_ready = pyqtSignal(object)
    health_ready = pyqtSignal(object)
    cli_response = pyqtSignal(str)
    cli_response_from = pyqtSignal(str, str)
    connection_changed = pyqtSignal(bool, str)
    nodes_changed = pyqtSignal(object)
    selected_node_changed = pyqtSignal(str)
    wifi_server_changed = pyqtSignal(bool, str)
    error_raised = pyqtSignal(str)
    display_clear_requested = pyqtSignal()
    export_started = pyqtSignal(str, str, int)
    export_finished = pyqtSignal(str, str, str)
    ota_progress = pyqtSignal(str, int, int, str)
    ota_staged = pyqtSignal(str, str, str, bool)
    ota_state = pyqtSignal(str, str, str)
    ota_availability = pyqtSignal(bool, str)

    def __init__(
        self,
        transport_factory: Callable[[], Transport],
        settings: QSettings | None = None,
        gateway_listener_factory: Callable[[], GatewayListener] | None = None,
        wake_service_factory: Callable[[WifiServerConfig], UdpWakeService] | None = None,
    ) -> None:
        super().__init__()
        self._transport_factory = transport_factory
        self._settings = settings or QSettings("OpenAI", "STM32SensorHost")
        self._gateway_listener_factory = gateway_listener_factory or GatewayListener
        self._wake_service_factory = wake_service_factory or self._create_wake_service
        self._session_index = NodeSessionManager(
            _MAXIMUM_WIFI_SESSIONS,
            aliases=self._load_aliases(),
        )
        self._sessions: dict[str, _ManagedSession] = {}
        self._selected_node_id: str | None = None
        self._window_s = 10.0
        self._display_paused = False
        self._is_stopping = False
        self._recording_active = False
        self._recording_batch_path: Path | None = None
        self._segment_counts: dict[str, int] = {}
        self._export_counts: dict[str, int] = {}
        self._gateway_listener: GatewayListener | None = None
        self._wake_service: UdpWakeService | None = None
        self._accept_stop_event: threading.Event | None = None
        self._accept_thread: QThread | None = None
        self._accept_worker: GatewayAcceptWorker | None = None
        self._wifi_server_label = ""
        self._timer = QTimer(self)
        self._timer.setInterval(_SNAPSHOT_INTERVAL_MS)
        self._timer.timeout.connect(self._publish_snapshots)
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(_STATUS_INTERVAL_MS)
        self._status_timer.timeout.connect(self._request_status)
        self._ota_reconnect: dict[str, object] | None = None
        self._ota_reconnect_timer = QTimer(self)
        self._ota_reconnect_timer.setInterval(_OTA_RECONNECT_POLL_MS)
        self._ota_reconnect_timer.timeout.connect(self._poll_ota_reconnect)
        # Controller-level OTA tracking survives a session teardown so the
        # expected post-STAGED reset disconnect is never reported as a failure.
        self._ota_node_id: str | None = None
        self._ota_thread: QThread | None = None
        self._ota_worker: "OtaUploadWorker | None" = None
        self._ota_cancel_event: threading.Event | None = None
        self._ota_context: dict[str, object] | None = None

    @property
    def is_running(self) -> bool:
        """Return whether any physical acquisition worker is running."""
        return any(session.thread.isRunning() for session in self._sessions.values())

    @property
    def selected_node_id(self) -> str | None:
        """Return the node receiving commands and driving detail views."""
        return self._selected_node_id

    @property
    def is_wifi_server_running(self) -> bool:
        """Return whether the gateway accept worker is active."""
        return self._accept_thread is not None and self._accept_thread.isRunning()

    @pyqtSlot(object)
    def start_wifi_server(self, config: WifiServerConfig) -> None:
        """Start TCP listening and periodic UDP wake for Wi-Fi field mode."""
        if self._sessions or self.is_wifi_server_running:
            self.error_raised.emit("disconnect current sessions before starting Wi-Fi")
            return
        listener = self._gateway_listener_factory()
        try:
            listener.start(config.local_ipv4, config.tcp_port)
            wake_service = self._wake_service_factory(config)
            wake_service.start()
        except (OSError, RuntimeError, ValueError) as error:
            listener.close()
            self.error_raised.emit(str(error))
            return
        self._save_wifi_config(config)
        stop_event = threading.Event()
        thread = QThread(self)
        worker = GatewayAcceptWorker(listener, stop_event)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.client_accepted.connect(self._accept_gateway_envelope)
        worker.failed.connect(self.error_raised)
        worker.stopped.connect(thread.quit, Qt.ConnectionType.DirectConnection)
        self._gateway_listener = listener
        self._wake_service = wake_service
        self._accept_stop_event = stop_event
        self._accept_thread = thread
        self._accept_worker = worker
        self._wifi_server_label = f"LISTENING {config.local_ipv4}:{config.tcp_port}"
        thread.start()
        self.wifi_server_changed.emit(True, self._wifi_server_label)

    @pyqtSlot()
    def stop_wifi_server(self) -> None:
        """Stop the listener, wake service and all accepted gateway sessions."""
        self._stop_wifi_resources()
        if self._sessions:
            self.disconnect_device()
        self.wifi_server_changed.emit(False, "DISCONNECTED")

    @pyqtSlot(str)
    def connect_device(self, device_id: str) -> None:
        """Open the single permitted CDC debug session."""
        if self.is_wifi_server_running:
            self.error_raised.emit("stop the Wi-Fi listener before opening CDC")
            return
        if self._sessions:
            self.error_raised.emit("disconnect current sessions before opening CDC")
            return
        transport = self._transport_factory()
        try:
            transport.open(device_id)
            self._add_session(
                node_id=f"cdc:{device_id}",
                peer=device_id,
                transport_kind=TransportKind.CDC,
                transport=transport,
            )
        except (OSError, RuntimeError, ValueError) as error:
            transport.close()
            self.error_raised.emit(str(error))
            self.connection_changed.emit(False, device_id)

    @pyqtSlot(object)
    def accept_gateway_client(self, client: AcceptedGatewayClient) -> None:
        """Start one independent session for an accepted ESP client."""
        has_cdc = any(
            session.transport_kind is TransportKind.CDC
            for session in self._sessions.values()
        )
        if has_cdc:
            client.transport.close()
            self._release_gateway_client(client.connection_id)
            self.error_raised.emit("disconnect CDC before accepting Wi-Fi gateways")
            return
        try:
            self._add_session(
                node_id=client.connection_id,
                peer=client.peer,
                transport_kind=TransportKind.WIFI,
                transport=client.transport,
            )
        except (RuntimeError, ValueError) as error:
            client.transport.close()
            self._release_gateway_client(client.connection_id)
            self.error_raised.emit(str(error))

    @pyqtSlot(object)
    def _accept_gateway_envelope(self, envelope: object) -> None:
        """Ignore a client queued by a listener that has since stopped."""
        source_listener, client = envelope  # type: ignore[misc]
        if source_listener is not self._gateway_listener:
            client.transport.close()
            source_listener.release(client.connection_id)
            return
        self.accept_gateway_client(client)

    def _add_session(
        self,
        node_id: str,
        peer: str,
        transport_kind: TransportKind,
        transport: Transport,
    ) -> None:
        self._session_index.add_session(node_id, transport_kind, peer)
        store = RealtimeSampleStore()
        acquisition = AcquisitionController(transport, store)
        if self._recording_active:
            acquisition.defer_recording_until_identity()
        acquisition.request_uuid()
        acquisition.request_status()
        acquisition.request_livestream()
        stop_event = threading.Event()
        thread = QThread(self)
        worker = AcquisitionWorker(acquisition, stop_event)
        worker.moveToThread(thread)
        session = _ManagedSession(
            node_id=node_id,
            peer=peer,
            transport_kind=transport_kind,
            transport=transport,
            store=store,
            acquisition=acquisition,
            stop_event=stop_event,
            thread=thread,
            worker=worker,
        )
        self._sessions[node_id] = session
        thread.started.connect(worker.run)
        worker.stopped.connect(thread.quit, Qt.ConnectionType.DirectConnection)
        # Queued callbacks from a closed CDC session must not affect a new
        # connection that reuses the same port/node id.
        worker.failed.connect(
            lambda message, expected=session: self._on_worker_failed(
                expected.node_id, message
            ) if self._sessions.get(expected.node_id) is expected else None
        )
        thread.finished.connect(
            lambda expected=session: self._on_thread_finished(expected.node_id)
            if self._sessions.get(expected.node_id) is expected else None
        )
        thread.start()
        if self._selected_node_id is None:
            self.select_node(node_id)
        self._timer.start()
        self._status_timer.start()
        self.connection_changed.emit(True, peer)
        self._emit_nodes()

    @pyqtSlot()
    def disconnect_device(self) -> None:
        """Stop every current session without leaving worker threads behind."""
        self._is_stopping = True
        self._stop_wifi_resources()
        self._timer.stop()
        self._status_timer.stop()
        self._ota_reconnect_timer.stop()
        self._ota_reconnect = None
        if self._ota_cancel_event is not None:
            self._ota_cancel_event.set()
        sessions = list(self._sessions.values())
        for session in sessions:
            self._update_recorder_disconnect_metadata(session, "user_disconnect")
            session.stop_event.set()
            session.transport.close()
            session.thread.quit()
        for session in sessions:
            if not session.thread.wait(_THREAD_STOP_TIMEOUT_MS):
                self.error_raised.emit(
                    f"acquisition thread for {session.peer} did not stop within three seconds"
                )
            self._finalize_session_recorders(session)
            session.worker.deleteLater()
            session.thread.deleteLater()
            self._session_index.remove(session.node_id)
        self._teardown_ota_worker()
        self._clear_ota_context()
        self._sessions.clear()
        self._selected_node_id = None
        self._recording_active = False
        self._recording_batch_path = None
        self._is_stopping = False
        self._emit_nodes()
        self.connection_changed.emit(False, "")
        self.display_clear_requested.emit()

    @pyqtSlot(str)
    def select_node(self, node_id: str) -> None:
        """Select one existing node as the detail and command target."""
        if node_id not in self._sessions:
            self.error_raised.emit(f"unknown node: {node_id}")
            return
        self._selected_node_id = node_id
        self.selected_node_changed.emit(node_id)
        self._publish_selected_session()
        self._emit_ota_availability()

    @pyqtSlot(str)
    def remove_offline_node(self, node_id: str) -> None:
        """Remove one inactive Wi-Fi node from the displayed inventory."""
        if node_id in self._sessions:
            self.error_raised.emit("cannot remove a connected device")
            return
        try:
            summary = self._session_index.summary(node_id)
        except KeyError:
            self.error_raised.emit(f"unknown node: {node_id}")
            return
        removable_states = {ConnectionState.OFFLINE, ConnectionState.RECONNECTING}
        if (
            summary.transport_kind is not TransportKind.WIFI
            or summary.connection_state not in removable_states
        ):
            self.error_raised.emit("only disconnected Wi-Fi devices can be removed")
            return
        self._session_index.remove(node_id)
        self._emit_nodes()

    @pyqtSlot(str)
    def send_command(self, command: str) -> None:
        """Queue one command only for the explicitly selected node."""
        if self._selected_node_id is None:
            self.error_raised.emit("select a connected node before sending commands")
            return
        self.send_command_to(self._selected_node_id, command)

    def send_command_to(self, node_id: str, command: str) -> None:
        """Queue one control command for an explicit node identifier."""
        session = self._sessions.get(node_id)
        if session is None:
            self.error_raised.emit(f"unknown node: {node_id}")
            return
        try:
            if command.strip().upper().startswith("AT+EXPORT"):
                self._start_archive_recording(session)
            session.acquisition.enqueue_command(command)
        except (OSError, RuntimeError, ValueError) as error:
            self.error_raised.emit(str(error))

    @pyqtSlot()
    def start_acquisition(self) -> None:
        """Start acquisition on the selected connected node."""
        if self._selected_node_id is None:
            self.error_raised.emit(
                "select a connected node before starting acquisition"
            )
            return
        self.start_acquisition_for(self._selected_node_id)

    def start_acquisition_for(self, node_id: str) -> None:
        """Queue START for an explicit connected node identifier."""
        session = self._sessions.get(node_id)
        if session is None:
            self.error_raised.emit(f"unknown node: {node_id}")
            return
        if session.ota_active or session.ota_awaiting_restart:
            self.error_raised.emit("OTA in progress; acquisition start is blocked")
            return
        session.acquisition.start_acquisition()

    @pyqtSlot()
    def stop_acquisition(self) -> None:
        """Stop acquisition on the selected connected node."""
        if self._selected_node_id is None:
            self.error_raised.emit(
                "select a connected node before stopping acquisition"
            )
            return
        self.stop_acquisition_for(self._selected_node_id)

    def stop_acquisition_for(self, node_id: str) -> None:
        """Queue STOP for an explicit connected node identifier."""
        session = self._sessions.get(node_id)
        if session is None:
            self.error_raised.emit(f"unknown node: {node_id}")
            return
        session.acquisition.stop_acquisition()

    @pyqtSlot(int)
    def set_watermark(self, words: int) -> None:
        """Set the watermark only on the selected node."""
        if self._selected_node_id is None:
            return
        self.set_watermark_for(self._selected_node_id, words)

    def set_watermark_for(self, node_id: str, words: int) -> None:
        """Queue a watermark update for an explicit node identifier."""
        session = self._sessions.get(node_id)
        if session is None:
            self.error_raised.emit(f"unknown node: {node_id}")
            return
        try:
            session.acquisition.set_watermark(words)
        except ValueError as error:
            self.error_raised.emit(str(error))

    @pyqtSlot(str)
    def set_livestream(self, target: str) -> None:
        """Manually select the live target on the selected node."""
        if self._selected_node_id is None:
            self.error_raised.emit("select a connected node before choosing a live target")
            return
        self.set_livestream_for(self._selected_node_id, target)

    def set_livestream_for(self, node_id: str, target: str) -> None:
        """Queue a live-target change for an explicit node identifier."""
        session = self._sessions.get(node_id)
        if session is None:
            self.error_raised.emit(f"unknown node: {node_id}")
            return
        try:
            session.acquisition.set_livestream(target)
        except ValueError as error:
            self.error_raised.emit(str(error))

    @pyqtSlot()
    def request_livestream(self) -> None:
        """Query the selected node without changing its live target."""
        session = self._selected_session()
        if session is not None:
            session.acquisition.request_livestream()

    def sd_records(self) -> list[SdRecordInfo]:
        """Return one virtual SD ring record per connected session."""
        records: list[SdRecordInfo] = []
        for session in self._sessions.values():
            summary = self._session_index.summary(session.node_id)
            state = session.store.snapshot(1.0, 2).firmware_control_state
            retained_frames = None if state is None else state.sd_retained_frames
            records.append(
                SdRecordInfo(
                    node_id=session.node_id,
                    alias=summary.alias,
                    uuid_suffix=(
                        str(summary.device_uuid)[-8:]
                        if summary.device_uuid is not None
                        else "PENDING"
                    ),
                    transport=session.transport_kind.value,
                    sd_ready=None if state is None else state.sd_ready,
                    sd_format_required=(
                        None if state is None else state.sd_format_required
                    ),
                    used_bytes=None if state is None else state.sd_used,
                    capacity_bytes=None if state is None else state.sd_capacity,
                    retained_frames=retained_frames,
                    retained_chunks=(
                        None if state is None else state.sd_retained_chunks
                    ),
                    overwritten_frames=(
                        None if state is None else state.sd_overwritten_frames
                    ),
                    estimated_duration_s=(
                        None
                        if retained_frames is None
                        else retained_frames / _IIS_SAMPLE_RATE_HZ
                    ),
                    export_phase=None if state is None else state.export_phase,
                )
            )
        return records

    def request_status_all(self) -> None:
        """Queue a firmware status request on every connected session."""
        for session in self._sessions.values():
            session.acquisition.request_status()

    def active_export_node(self) -> str | None:
        """Return the node with an archive export currently recording."""
        for session in self._sessions.values():
            if session.archive_recorder is not None:
                return session.node_id
        return None

    def start_export_for(self, node_id: str) -> None:
        """Start one archive export on the node's own transport path."""
        session = self._sessions.get(node_id)
        if session is None:
            self.error_raised.emit(f"unknown node: {node_id}")
            return
        if session.ota_active or session.ota_awaiting_restart:
            self.error_raised.emit("OTA in progress; export is blocked")
            return
        if session.archive_recorder is not None:
            self.error_raised.emit("an archive export is already active for this node")
            return
        state = session.store.snapshot(1.0, 2).firmware_control_state
        if state is None or not state.sd_ready:
            self.error_raised.emit(
                "device SD is not ready; refresh status before exporting"
            )
            return
        if state.acquisition_state not in (None, "IDLE"):
            self.error_raised.emit(
                "stop acquisition before exporting; the firmware rejects "
                f"export while {state.acquisition_state}"
            )
            return
        target = (
            "CDC" if session.transport_kind is TransportKind.CDC else "UART"
        )
        try:
            path = self._start_archive_recording(session)
        except (OSError, RuntimeError, ValueError) as error:
            self.error_raised.emit(str(error))
            return
        session.archive_total_bytes = state.sd_used or 0
        session.archive_path = path
        session.archive_target = target
        session.archive_retries = 0
        session.archive_cancel_requested = False
        session.acquisition.enqueue_command(f"AT+EXPORT={target}")
        self.export_started.emit(node_id, str(path), session.archive_total_bytes)

    def cancel_export_for(self, node_id: str) -> None:
        """Cancel the node's active export; firmware stops in EXPORT state."""
        session = self._sessions.get(node_id)
        if session is None:
            self.error_raised.emit(f"unknown node: {node_id}")
            return
        if session.archive_recorder is None:
            return
        if session.archive_cancel_requested:
            return
        session.archive_cancel_requested = True
        session.acquisition.stop_acquisition()
        # The firmware acknowledges EXPORT+STOP with a bare OK.  Follow it with
        # a state query so the host can confirm IDLE/NONE before closing its
        # local recorder.
        session.acquisition.request_status()

    def clear_sd_for(self, node_id: str) -> None:
        """Clear one device's SD ring after the firmware state gate passes."""
        session = self._sessions.get(node_id)
        if session is None:
            self.error_raised.emit(f"unknown node: {node_id}")
            return
        if session.archive_recorder is not None:
            self.error_raised.emit("cancel the active export before clearing device SD")
            return
        state = session.store.snapshot(1.0, 2).firmware_control_state
        if state is None:
            self.error_raised.emit(
                "refresh status before clearing device SD"
            )
            return
        if state.acquisition_state not in {"IDLE", "ERROR"}:
            self.error_raised.emit(
                "device SD can only be cleared while IDLE or ERROR; "
                f"current state is {state.acquisition_state}"
            )
            return
        try:
            session.acquisition.clear_sd()
        except (RuntimeError, ValueError) as error:
            self.error_raised.emit(str(error))

    def export_status(self, node_id: str) -> tuple[bool, int, int, str | None]:
        """Return (active, bytes_written, total_bytes, phase) for one node."""
        session = self._sessions.get(node_id)
        if session is None:
            return (False, 0, 0, None)
        state = session.store.snapshot(1.0, 2).firmware_control_state
        phase = None if state is None else state.export_phase
        recorder = session.archive_recorder
        if recorder is None:
            return (False, 0, session.archive_total_bytes, phase)
        return (True, recorder.bytes_written, session.archive_total_bytes, phase)

    def ota_active_node(self) -> str | None:
        """Return the node with an OTA upload or post-staged reconnect active."""
        return self._ota_node_id

    def ota_in_progress(self, node_id: str) -> bool:
        """Return whether OTA owns the given node (uploading or awaiting reboot)."""
        session = self._sessions.get(node_id)
        if session is not None and (session.ota_active or session.ota_awaiting_restart):
            return True
        return self._ota_node_id == node_id

    def start_ota_for(self, node_id: str, package: "OtaPackage | str | Path") -> None:
        """Validate guards, self-check the package, and start one OTA upload.

        ``package`` may be a path to a ``.ota`` file or an already-built
        :class:`OtaPackage` (e.g. produced by the dialog from a raw ``.bin``).
        """
        session = self._sessions.get(node_id)
        if session is None:
            self.error_raised.emit(f"unknown node: {node_id}")
            return
        if session.transport_kind is not TransportKind.WIFI:
            message = (
                "OTA 仅支持 UART 来源链路（Wi-Fi 网关）；"
                "CDC 会话会被固件以 ERROR:SOURCE 拒绝"
            )
            self.ota_state.emit(node_id, "SOURCE_REJECTED", message)
            self.error_raised.emit(message)
            return
        if self._ota_node_id is not None:
            self.error_raised.emit("an OTA session is already in progress")
            return
        if session.archive_recorder is not None:
            self.error_raised.emit("cancel the active export before starting OTA")
            return
        if self._recording_active:
            self.error_raised.emit("stop recording before starting OTA")
            return
        state = session.store.snapshot(1.0, 2).firmware_control_state
        if state is None:
            self.error_raised.emit("refresh device status before starting OTA")
            return
        if not state.sd_ready or state.sd_format_required:
            self.error_raised.emit(
                "device SD must be READY and not require format before OTA"
            )
            return
        try:
            ota_package = (
                package
                if isinstance(package, OtaPackage)
                else load_package(package)
            )
        except (OtaPackageError, OSError) as error:
            self.ota_state.emit(node_id, "PACKAGE_REJECTED", str(error))
            self.error_raised.emit(str(error))
            return
        if state.acquisition_state == "ACQUIRE":
            self.ota_state.emit(
                node_id,
                "STOPPING_ACQUISITION",
                "设备正在采集，固件将先停止采集再进入 OTA",
            )
        summary = self._session_index.summary(node_id)
        cancel_event = threading.Event()
        session.ota_active = True
        self._ota_node_id = node_id
        self._ota_cancel_event = cancel_event
        self._ota_context = {
            "node_id": node_id,
            "kind": session.transport_kind,
            "device_uuid": summary.device_uuid,
            "device_id": session.peer,
            "version": ota_package.version_text,
            "crc": ota_package.crc_text,
        }
        session.acquisition.start_ota()
        thread = QThread(self)
        worker = OtaUploadWorker(
            node_id, session.acquisition, ota_package.data, cancel_event
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_ota_progress)
        worker.staged.connect(self._on_ota_staged)
        worker.failed.connect(self._on_ota_failed)
        worker.cancelled.connect(self._on_ota_cancelled)
        worker.stopped.connect(thread.quit, Qt.ConnectionType.DirectConnection)
        self._ota_thread = thread
        self._ota_worker = worker
        thread.start()
        label = (
            Path(package).name
            if isinstance(package, (str, Path))
            else f"{ota_package.version_text} (auto-packaged)"
        )
        self.ota_state.emit(node_id, "STARTED", f"开始上传 {label}")
        self._emit_ota_availability()

    def cancel_ota_for(self, node_id: str) -> None:
        """Request cooperative cancellation; the uploader sends a CANCEL frame."""
        if self._ota_node_id == node_id and self._ota_cancel_event is not None:
            self._ota_cancel_event.set()

    @pyqtSlot(str, int, int, str)
    def _on_ota_progress(self, node_id: str, sent: int, total: int, phase: str) -> None:
        self.ota_progress.emit(node_id, sent, total, phase)

    @pyqtSlot(str, object)
    def _on_ota_staged(self, node_id: str, result: object) -> None:
        payload = result if isinstance(result, dict) else {}
        staged_version = str(payload.get("staged_version") or "")
        staged_crc = payload.get("staged_crc")
        staged_crc_text = format_crc(staged_crc) if isinstance(staged_crc, int) else ""
        context = self._ota_context or {}
        expected_version = str(context.get("version") or "")
        expected_crc = str(context.get("crc") or "")
        session = self._sessions.get(node_id)
        if session is not None:
            session.ota_active = False
            session.ota_awaiting_restart = True
            session.acquisition.end_ota()
        matches = (
            staged_version == expected_version and staged_crc_text == expected_crc
        )
        self.ota_staged.emit(node_id, staged_version, staged_crc_text, matches)
        if not matches:
            self.error_raised.emit(
                "设备回读的 STAGED 与本地包不一致（设备 "
                f"{staged_version}/{staged_crc_text} vs 本地 "
                f"{expected_version}/{expected_crc}）"
            )
        self.ota_state.emit(
            node_id,
            "WAIT_RESTART",
            "镜像已暂存，设备将自动复位并从 SD 安装；等待设备重启…",
        )
        self._teardown_ota_worker()
        self._arm_ota_reconnect()
        self._emit_ota_availability()

    @pyqtSlot(str, str, str)
    def _on_ota_failed(self, node_id: str, code: str, message: str) -> None:
        session = self._sessions.get(node_id)
        if session is not None:
            session.ota_active = False
            session.acquisition.end_ota()
        self._teardown_ota_worker()
        self._clear_ota_context()
        detail = describe_nack(code) if code else message
        self.ota_state.emit(node_id, "FAILED", detail)
        self.error_raised.emit(
            f"OTA 失败：{detail}（{message}）" if code else f"OTA 失败：{message}"
        )
        self._emit_ota_availability()

    @pyqtSlot(str)
    def _on_ota_cancelled(self, node_id: str) -> None:
        session = self._sessions.get(node_id)
        if session is not None:
            session.ota_active = False
            session.acquisition.end_ota()
        self._teardown_ota_worker()
        self._clear_ota_context()
        self.ota_state.emit(node_id, "CANCELLED", "已发送 CANCEL，OTA 会话已取消")
        self._emit_ota_availability()

    def _teardown_ota_worker(self) -> None:
        thread = self._ota_thread
        worker = self._ota_worker
        self._ota_thread = None
        self._ota_worker = None
        self._ota_cancel_event = None
        if thread is not None:
            thread.quit()
            thread.wait(_THREAD_STOP_TIMEOUT_MS)
            if worker is not None:
                worker.deleteLater()
            thread.deleteLater()

    def _clear_ota_context(self) -> None:
        self._ota_context = None
        self._ota_node_id = None

    def _arm_ota_reconnect(self) -> None:
        context = self._ota_context
        if context is None:
            return
        self._ota_reconnect = {
            "kind": context["kind"],
            "device_uuid": context["device_uuid"],
            "device_id": context["device_id"],
            "node_id": context["node_id"],
            "deadline_s": time.monotonic() + _OTA_RECONNECT_TIMEOUT_S,
        }
        self._ota_reconnect_timer.start()

    @pyqtSlot()
    def _poll_ota_reconnect(self) -> None:
        info = self._ota_reconnect
        if info is None:
            self._ota_reconnect_timer.stop()
            return
        if time.monotonic() > float(info["deadline_s"]):
            self._finish_ota_reconnect(
                "RECONNECT_TIMEOUT", "设备复位后未在预期时间内重连"
            )
            return
        if info["kind"] is TransportKind.CDC and not self._sessions:
            self._attempt_ota_cdc_reopen(str(info["device_id"] or ""))
        expected_uuid = info["device_uuid"]
        for session in self._sessions.values():
            summary = self._session_index.summary(session.node_id)
            if summary.connection_state not in (
                ConnectionState.CONNECTED,
                ConnectionState.STREAMING,
            ):
                continue
            if expected_uuid is not None and summary.device_uuid != expected_uuid:
                continue
            session.acquisition.request_status()
            state = session.store.snapshot(1.0, 2).firmware_control_state
            if state is not None and state.ota_state in (None, "OFF"):
                self._finish_ota_reconnect(
                    "RECONNECTED", "设备已重连，OTA 状态 OFF，实时流恢复"
                )
                return

    def _attempt_ota_cdc_reopen(self, device_id: str) -> None:
        if not device_id or self._sessions or self.is_wifi_server_running:
            return
        transport = self._transport_factory()
        try:
            transport.open(device_id)
        except (OSError, RuntimeError, ValueError):
            transport.close()
            return
        self._add_session(
            node_id=f"cdc:{device_id}",
            peer=device_id,
            transport_kind=TransportKind.CDC,
            transport=transport,
        )

    def _finish_ota_reconnect(self, status: str, detail: str) -> None:
        self._ota_reconnect_timer.stop()
        info = self._ota_reconnect
        self._ota_reconnect = None
        node_id = str(info["node_id"]) if info else (self._ota_node_id or "")
        self._clear_ota_context()
        self.ota_state.emit(node_id, status, detail)
        if status != "RECONNECTED":
            self.error_raised.emit(detail)
        self._emit_ota_availability()

    def _emit_ota_availability(self) -> None:
        if self._ota_node_id is not None:
            self.ota_availability.emit(False, "OTA session in progress")
            return
        session = self._selected_session()
        if session is None:
            self.ota_availability.emit(False, "connect a Wi-Fi node to update firmware")
            return
        if session.transport_kind is not TransportKind.WIFI:
            self.ota_availability.emit(
                False, "OTA 仅支持 UART 来源链路（Wi-Fi 网关）"
            )
            return
        self.ota_availability.emit(True, "")

    @pyqtSlot(bool)
    def set_display_paused(self, paused: bool) -> None:
        self._display_paused = paused

    @pyqtSlot()
    def clear_display_samples(self) -> None:
        """Clear only the selected node's plot buffer; recording is independent."""
        session = self._selected_session()
        if session is not None:
            session.store.clear_samples()

    @pyqtSlot(float)
    def set_window_seconds(self, window_s: float) -> None:
        if window_s > 0.0:
            self._window_s = window_s

    def set_recording(self, enabled: bool, path: Path | None = None) -> None:
        """Start or stop separate raw recordings for all current sessions."""
        if enabled:
            if not self._sessions:
                self.error_raised.emit("connect before starting a recording")
                return
            if self._recording_active:
                return
            if any(
                session.ota_active or session.ota_awaiting_restart
                for session in self._sessions.values()
            ):
                self.error_raised.emit("OTA in progress; recording is blocked")
                return
            self._recording_active = True
            self._recording_batch_path = path or self._default_recording_batch_path()
            for session in self._sessions.values():
                summary = self._session_index.summary(session.node_id)
                if summary.device_uuid is not None:
                    self._start_session_recording(session)
            self._emit_nodes()
            return
        self._recording_active = False
        for session in self._sessions.values():
            self._stop_session_recording(session)
        self._recording_batch_path = None
        self._emit_nodes()

    def set_alias(self, node_id: str, alias: str) -> None:
        """Update and persist the display alias for an identified node."""
        try:
            summary = self._session_index.set_alias(node_id, alias)
        except (KeyError, ValueError) as error:
            self.error_raised.emit(str(error))
            return
        if summary.device_uuid is not None:
            self._settings.setValue(f"aliases/{summary.device_uuid}", summary.alias)
        self._emit_nodes()

    @pyqtSlot()
    def _publish_snapshots(self) -> None:
        for session in list(self._sessions.values()):
            self._consume_identity_updates(session)
            responses = session.acquisition.drain_cli_responses()
            for response in responses:
                self.cli_response_from.emit(session.node_id, response)
            if session.node_id == self._selected_node_id:
                for response in responses:
                    self.cli_response.emit(response)
            self._finalize_completed_export(session)
            self._watchdog_stalled_export(session)
        self._publish_selected_session()

    def _publish_selected_session(self) -> None:
        session = self._selected_session()
        if session is None:
            return
        self.health_ready.emit(session.acquisition.health)
        if not self._display_paused:
            self.snapshot_ready.emit(
                session.store.snapshot(
                    self._window_s,
                    max_points=_MAXIMUM_DISPLAY_POINTS,
                )
            )

    @pyqtSlot()
    def _request_status(self) -> None:
        for session in self._sessions.values():
            # Keep UART/CDC TX free for archive frames while an export runs;
            # status replies would contend for the same transmit path.
            if session.archive_recorder is None and not session.ota_active:
                session.acquisition.request_status()

    def _consume_identity_updates(self, session: _ManagedSession) -> None:
        for device_uuid in session.acquisition.drain_identity_updates():
            try:
                self._session_index.bind_identity(session.node_id, device_uuid)
            except DuplicateDeviceError as error:
                session.failure = str(error)
                session.stop_event.set()
                session.transport.close()
                self.error_raised.emit(str(error))
                return
            if self._recording_active and session.recorder is None:
                self._start_session_recording(session)
            self._emit_nodes()

    @pyqtSlot(str, str)
    def _on_worker_failed(self, node_id: str, message: str) -> None:
        session = self._sessions.get(node_id)
        if session is not None:
            session.failure = message
            self._update_recorder_disconnect_metadata(session, message)
        # A post-STAGED device reset drops the link on purpose; never surface it
        # as an error while an OTA upload/reconnect owns this node.
        ota_inflight = (
            self._ota_context is not None
            and self._ota_context.get("node_id") == node_id
        )
        awaiting_restart = session is not None and session.ota_awaiting_restart
        if not self._is_stopping and not ota_inflight and not awaiting_restart:
            self.error_raised.emit(message)

    @pyqtSlot(str)
    def _on_thread_finished(self, node_id: str) -> None:
        if self._is_stopping:
            return
        session = self._sessions.pop(node_id, None)
        if session is None:
            return
        self._finalize_session_recorders(session)
        if session.transport_kind is TransportKind.WIFI:
            self._release_gateway_client(node_id)
            self._session_index.mark_reconnecting(node_id, session.failure)
        else:
            self._session_index.mark_offline(node_id, session.failure)
        session.worker.deleteLater()
        session.thread.deleteLater()
        target_replaced = self._selected_node_id == node_id
        if target_replaced:
            self._selected_node_id = next(iter(self._sessions), None)
        self._emit_nodes()
        if target_replaced:
            # Keep the sidebar highlight on the authoritative target after an
            # automatic fail-over so the visible target never drifts (UI-01).
            self.selected_node_changed.emit(self._selected_node_id or "")
        if not self._sessions:
            self._timer.stop()
            self._status_timer.stop()
            if self.is_wifi_server_running:
                self.wifi_server_changed.emit(True, self._wifi_server_label)
            else:
                self.connection_changed.emit(False, "")
            self.display_clear_requested.emit()

    def _selected_session(self) -> _ManagedSession | None:
        if self._selected_node_id is None:
            return None
        return self._sessions.get(self._selected_node_id)

    def _emit_nodes(self) -> None:
        self.nodes_changed.emit(self._session_index.summaries())
        self._emit_ota_availability()

    def _start_session_recording(
        self,
        session: _ManagedSession,
    ) -> None:
        if session.recorder is not None:
            return
        summary = self._session_index.summary(session.node_id)
        identity = str(summary.device_uuid) if summary.device_uuid is not None else session.node_id
        segment_number = self._segment_counts.get(identity, 0) + 1
        self._segment_counts[identity] = segment_number
        output_path = self._recording_path(summary, segment_number)
        recorder = RawSessionRecorder()
        try:
            recorder.start(
                output_path,
                {
                    "format": "SDF1",
                    "transport": session.transport_kind.value,
                    "peer": session.peer,
                    "uuid": str(summary.device_uuid) if summary.device_uuid else None,
                    "alias": summary.alias,
                    "segment": segment_number,
                },
            )
        except OSError as error:
            self.error_raised.emit(str(error))
            return
        session.recorder = recorder
        session.acquisition.set_recorder(recorder)
        self._session_index.set_recording(session.node_id, True)

    def _stop_session_recording(self, session: _ManagedSession) -> None:
        recorder = session.recorder
        if recorder is None:
            session.acquisition.cancel_deferred_recording()
            return
        session.acquisition.set_recorder(None)
        session.recorder = None
        try:
            recorder.stop()
        except RuntimeError as error:
            self.error_raised.emit(str(error))
        self._session_index.set_recording(session.node_id, False)

    def _start_archive_recording(self, session: _ManagedSession) -> Path:
        if session.archive_recorder is not None:
            raise RuntimeError("an archive export is already active for this node")
        summary = self._session_index.summary(session.node_id)
        if summary.device_uuid is None:
            raise RuntimeError("wait for node UUID before exporting an archive")
        stamp = self._utc_stamp()
        identity = str(summary.device_uuid)
        export_number = self._export_counts.get(identity, 0) + 1
        self._export_counts[identity] = export_number
        path = (
            data_root()
            / "exports"
            / stamp
            / self._safe_node_directory(summary)
            / f"export-{export_number:03d}.sdf1"
        )
        recorder = RawSessionRecorder()
        recorder.start(
            path,
            {
                "format": "SDF1_ARCHIVE_EXPORT",
                "transport": session.transport_kind.value,
                "peer": session.peer,
                "uuid": str(summary.device_uuid),
                "alias": summary.alias,
                "status": "in_progress",
            },
        )
        session.archive_recorder = recorder
        state = session.store.snapshot(1.0, 2).firmware_control_state
        session.archive_start_revision = 0 if state is None else state.export_revision
        session.archive_started_s = time.monotonic()
        session.acquisition.set_archive_recorder(recorder)
        return path

    def _finalize_completed_export(self, session: _ManagedSession) -> None:
        recorder = session.archive_recorder
        if recorder is None:
            return
        state = session.store.snapshot(1.0, 2).firmware_control_state
        phase = None if state is None else state.export_phase
        revision = 0 if state is None else state.export_revision
        cancel_confirmed = (
            session.archive_cancel_requested
            and state is not None
            and state.acquisition_state == "IDLE"
            and state.export_target == "NONE"
        )
        if cancel_confirmed:
            phase = "ABORTED"
        elif (
            phase not in {"EMPTY", "COMPLETE", "ABORTED"}
            or revision <= session.archive_start_revision
        ):
            return
        recorder.update_metadata(
            {
                "status": phase.lower(),
                "export_chunks": None if state is None else state.export_chunks,
                "export_frames": None if state is None else state.export_frames,
            }
        )
        session.acquisition.set_archive_recorder(None)
        session.archive_recorder = None
        explicitly_cancelled = cancel_confirmed
        session.archive_cancel_requested = False
        try:
            summary = recorder.stop()
        except RuntimeError as error:
            self.error_raised.emit(str(error))
            return
        if phase == "ABORTED" and summary.bytes_written == 0 and not explicitly_cancelled:
            if session.archive_retries < _EXPORT_AUTO_RETRIES:
                session.archive_retries += 1
                self._retry_export_after_abort(session)
                return
            self.error_raised.emit(
                "firmware aborted the export before transmitting any frame; "
                "retry after STOP and inspect the CONSOLE EXPORT_* lines"
            )
        elif phase == "EMPTY":
            self.error_raised.emit("device SD ring is empty; nothing to export")
        self.export_finished.emit(session.node_id, phase or "UNKNOWN", str(summary.path))

    def _retry_export_after_abort(self, session: _ManagedSession) -> None:
        """Re-arm one export after a zero-byte firmware abort (transient UART)."""
        target = session.archive_target or (
            "CDC" if session.transport_kind is TransportKind.CDC else "UART"
        )
        try:
            path = self._start_archive_recording(session)
        except (OSError, RuntimeError, ValueError) as error:
            self.error_raised.emit(str(error))
            return
        session.archive_path = path
        session.archive_target = target
        session.acquisition.enqueue_command(f"AT+EXPORT={target}")
        self.error_raised.emit(
            f"firmware aborted the export before the first frame; automatic "
            f"retry {session.archive_retries}/{_EXPORT_AUTO_RETRIES} started"
        )
        self.export_started.emit(
            session.node_id, str(path), session.archive_total_bytes
        )

    def _watchdog_stalled_export(self, session: _ManagedSession) -> None:
        """Detach an export that never received a single archive frame."""
        recorder = session.archive_recorder
        if (
            recorder is None
            or recorder.bytes_written
            or session.archive_cancel_requested
        ):
            return
        elapsed_s = time.monotonic() - session.archive_started_s
        if elapsed_s < _EXPORT_FIRST_BYTE_TIMEOUT_S:
            return
        state = session.store.snapshot(1.0, 2).firmware_control_state
        phase = None if state is None else state.export_phase
        if phase in {"COMPLETE", "EMPTY", "ABORTED"}:
            return
        session.acquisition.set_archive_recorder(None)
        session.archive_recorder = None
        try:
            recorder.update_metadata({"status": "stalled"})
            summary = recorder.stop()
        except RuntimeError as error:
            self.error_raised.emit(str(error))
            return
        self.error_raised.emit(
            "export stalled: no archive bytes within "
            f"{_EXPORT_FIRST_BYTE_TIMEOUT_S:.0f} s (firmware phase "
            f"{phase or 'unknown'}); check CONSOLE for EXPORT_/ERROR lines"
        )
        self.export_finished.emit(session.node_id, "STALLED", str(summary.path))

    def _finalize_session_recorders(self, session: _ManagedSession) -> None:
        recorder = session.recorder
        session.recorder = None
        if recorder is not None:
            session.acquisition.set_recorder(None)
            try:
                recorder.stop()
            except RuntimeError as error:
                self.error_raised.emit(str(error))
        archive_recorder = session.archive_recorder
        session.archive_recorder = None
        if archive_recorder is not None:
            session.acquisition.set_archive_recorder(None)
            try:
                archive_recorder.update_metadata({"status": "aborted"})
                archive_recorder.stop()
            except RuntimeError as error:
                self.error_raised.emit(str(error))

    def _recording_path(self, summary: NodeSummary, segment_number: int) -> Path:
        if self._recording_batch_path is None:
            raise RuntimeError("recording batch path is not configured")
        return (
            self._recording_batch_path
            / self._safe_node_directory(summary)
            / f"segment-{segment_number:03d}.sdf1"
        )

    @staticmethod
    def _safe_node_directory(summary: NodeSummary) -> str:
        alias = summary.alias or "node"
        uuid_suffix = (
            str(summary.device_uuid).replace("-", "")[:8]
            if summary.device_uuid is not None
            else "pending"
        )
        safe_alias = _SAFE_PATH_PATTERN.sub("-", alias).strip("-._") or "node"
        return f"{safe_alias}-{uuid_suffix}"

    @classmethod
    def _default_recording_batch_path(cls) -> Path:
        return data_root() / "recordings" / cls._utc_stamp()

    @staticmethod
    def _utc_stamp() -> str:
        return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    def _load_aliases(self) -> dict[str, str]:
        aliases: dict[str, str] = {}
        self._settings.beginGroup("aliases")
        try:
            for key in self._settings.childKeys():
                value = self._settings.value(key, "", type=str).strip()
                if value:
                    aliases[key] = value
        finally:
            self._settings.endGroup()
        return aliases

    def _save_wifi_config(self, config: WifiServerConfig) -> None:
        self._settings.setValue("wifi/local_ipv4", config.local_ipv4)
        self._settings.setValue("wifi/netmask", config.netmask)
        self._settings.setValue("wifi/expected_pc_ipv4", config.expected_pc_ipv4)
        self._settings.setValue("wifi/tcp_port", config.tcp_port)
        self._settings.setValue("wifi/udp_port", config.udp_port)
        self._settings.setValue("wifi/unicast_targets", list(config.unicast_targets))

    @staticmethod
    def _update_recorder_disconnect_metadata(
        session: _ManagedSession, reason: str
    ) -> None:
        if session.recorder is not None:
            session.recorder.update_metadata({"disconnect_reason": reason})
        if session.archive_recorder is not None:
            session.archive_recorder.update_metadata(
                {"status": "aborted", "disconnect_reason": reason}
            )

    def _stop_wifi_resources(self) -> None:
        stop_event = self._accept_stop_event
        listener = self._gateway_listener
        wake_service = self._wake_service
        thread = self._accept_thread
        worker = self._accept_worker
        self._accept_stop_event = None
        self._gateway_listener = None
        self._wake_service = None
        self._accept_thread = None
        self._accept_worker = None
        self._wifi_server_label = ""
        if stop_event is not None:
            stop_event.set()
        if listener is not None:
            listener.close()
        if wake_service is not None:
            wake_service.stop()
        if thread is not None:
            thread.quit()
            if not thread.wait(_THREAD_STOP_TIMEOUT_MS):
                self.error_raised.emit("gateway listener did not stop within three seconds")
            if worker is not None:
                worker.deleteLater()
            thread.deleteLater()

    def _release_gateway_client(self, connection_id: str) -> None:
        listener = self._gateway_listener
        if listener is not None:
            listener.release(connection_id)

    @staticmethod
    def _create_wake_service(config: WifiServerConfig) -> UdpWakeService:
        return UdpWakeService(
            local_ipv4=config.local_ipv4,
            netmask=config.netmask,
            udp_port=config.udp_port,
            unicast_targets=config.unicast_targets,
        )
