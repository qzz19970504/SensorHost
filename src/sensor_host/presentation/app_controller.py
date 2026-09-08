"""Qt lifecycle and multi-node coordination for host acquisition sessions."""

from __future__ import annotations

import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from PyQt6.QtCore import QObject, QSettings, QThread, QTimer, Qt, pyqtSignal, pyqtSlot

from sensor_host.acquisition import (
    AcquisitionController,
    DuplicateDeviceError,
    NodeSessionManager,
    NodeSummary,
    RealtimeSampleStore,
    TransportKind,
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
    failure: str | None = None


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
        self._sessions.clear()
        self._selected_node_id = None
        self._recording_active = False
        self._recording_batch_path = None
        self._is_stopping = False
        self._emit_nodes()
        self.connection_changed.emit(False, "")

    @pyqtSlot(str)
    def select_node(self, node_id: str) -> None:
        """Select one existing node as the detail and command target."""
        if node_id not in self._sessions:
            self.error_raised.emit(f"unknown node: {node_id}")
            return
        self._selected_node_id = node_id
        self.selected_node_changed.emit(node_id)
        self._publish_selected_session()

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
        if not self._is_stopping:
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

    def _selected_session(self) -> _ManagedSession | None:
        if self._selected_node_id is None:
            return None
        return self._sessions.get(self._selected_node_id)

    def _emit_nodes(self) -> None:
        self.nodes_changed.emit(self._session_index.summaries())

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

    def _start_archive_recording(self, session: _ManagedSession) -> None:
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
        session.acquisition.set_archive_recorder(recorder)

    def _finalize_completed_export(self, session: _ManagedSession) -> None:
        recorder = session.archive_recorder
        if recorder is None:
            return
        state = session.store.snapshot(1.0, 2).firmware_control_state
        phase = None if state is None else state.export_phase
        revision = 0 if state is None else state.export_revision
        if (
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
        try:
            recorder.stop()
        except RuntimeError as error:
            self.error_raised.emit(str(error))

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
