import queue
import struct
import time
import uuid
import zlib

from sensor_host import app as sensor_host_app
from sensor_host.acquisition import ConnectionState, NodeSummary, TransportKind
from sensor_host.presentation.app_controller import AppController
from sensor_host.presentation.main_window import MainWindow
from sensor_host.protocol import FirmwareControlState
from sensor_host.transport import AcceptedGatewayClient
from sensor_host.transport import WifiServerConfig

from test_archive_library import write_archive


def encode_jy_frame(
    device_uuid: uuid.UUID, sequence: int = 1, flags: int = 0
) -> bytes:
    payload = bytes(14)
    header = struct.pack(
        "<4sBBHHHIQHH",
        b"SDF1",
        2,
        2,
        flags,
        44,
        len(payload),
        sequence,
        100,
        1,
        0,
    ) + device_uuid.bytes
    content = header + payload
    return content + struct.pack("<I", zlib.crc32(content) & 0xFFFFFFFF)


def encode_cli_frame(text: str, sequence: int = 1) -> bytes:
    payload = text.encode()
    header = struct.pack(
        "<4sBBHHHIQHH",
        b"SDF1",
        1,
        4,
        0,
        28,
        len(payload),
        sequence,
        100,
        1,
        0,
    )
    content = header + payload
    return content + struct.pack("<I", zlib.crc32(content) & 0xFFFFFFFF)


class RecordingIdleTransport:
    def __init__(self) -> None:
        self.commands: list[bytes] = []
        self.is_closed = False

    def open(self, device_id: str) -> None:
        self.device_id = device_id

    def close(self) -> None:
        self.is_closed = True

    def read(self, max_bytes: int, timeout_s: float) -> bytes:
        return b""

    def write_control(self, command: bytes) -> None:
        self.commands.append(command)


class FailingReadTransport(RecordingIdleTransport):
    def read(self, max_bytes: int, timeout_s: float) -> bytes:
        raise OSError("device disconnected")


class SlowCloseTransport(RecordingIdleTransport):
    def close(self) -> None:
        time.sleep(0.2)
        super().close()


class QueueTransport(RecordingIdleTransport):
    def __init__(self) -> None:
        super().__init__()
        self.chunks: queue.Queue[bytes | OSError] = queue.Queue()

    def read(self, max_bytes: int, timeout_s: float) -> bytes:
        try:
            value = self.chunks.get(timeout=timeout_s)
        except queue.Empty:
            return b""
        if isinstance(value, OSError):
            raise value
        return value


def test_app_controller_stops_worker_thread(qtbot, fake_transport_factory) -> None:
    controller = AppController(fake_transport_factory)

    controller.connect_device("FAKE")
    qtbot.waitUntil(lambda: controller.is_running, timeout=1000)
    controller.disconnect_device()

    qtbot.waitUntil(lambda: not controller.is_running, timeout=2000)


def test_app_controller_requests_status_on_connect(qtbot) -> None:
    transport = RecordingIdleTransport()
    controller = AppController(lambda: transport)

    controller.connect_device("FAKE")
    try:
        qtbot.waitUntil(lambda: len(transport.commands) >= 3, timeout=1000)
        assert transport.commands[:3] == [
            b"AT+UUID?",
            b"AT+STATE?",
            b"AT+LIVESTREAM?",
        ]
    finally:
        controller.disconnect_device()


def test_selected_node_receives_start_and_stop_commands(qtbot) -> None:
    transport = RecordingIdleTransport()
    controller = AppController(lambda: transport)

    controller.connect_device("FAKE")
    try:
        qtbot.waitUntil(lambda: len(transport.commands) >= 3, timeout=1000)

        controller.start_acquisition()
        controller.stop_acquisition()

        qtbot.waitUntil(lambda: len(transport.commands) >= 5, timeout=1000)
        assert transport.commands[-2:] == [b"AT+START", b"AT+STOP"]
    finally:
        controller.disconnect_device()


def test_start_and_stop_require_a_selected_node(qtbot) -> None:
    controller = AppController(RecordingIdleTransport)
    errors: list[str] = []
    controller.error_raised.connect(errors.append)

    controller.start_acquisition()
    controller.stop_acquisition()

    assert errors == [
        "select a connected node before starting acquisition",
        "select a connected node before stopping acquisition",
    ]


def test_start_and_stop_reject_an_unknown_node(qtbot) -> None:
    controller = AppController(RecordingIdleTransport)
    errors: list[str] = []
    controller.error_raised.connect(errors.append)

    controller.start_acquisition_for("missing")
    controller.stop_acquisition_for("missing")

    assert errors == ["unknown node: missing", "unknown node: missing"]


def test_acquisition_widgets_are_wired_to_selected_node_commands(qtbot) -> None:
    transport = RecordingIdleTransport()
    controller = AppController(lambda: transport)
    window = MainWindow()
    qtbot.addWidget(window)

    sensor_host_app._wire_acquisition_controls(window, controller)
    controller.connect_device("FAKE")
    window.set_connected(True)
    window.set_nodes(
        [
            NodeSummary(
                node_id="cdc:FAKE",
                transport_kind=TransportKind.CDC,
                peer="FAKE",
                connection_state=ConnectionState.STREAMING,
                alias="FAKE",
            )
        ]
    )
    try:
        qtbot.waitUntil(lambda: len(transport.commands) >= 3, timeout=1000)

        window.start_button.click()
        window.stop_button.click()
        window.live_target_combo.setCurrentText("CDC")

        qtbot.waitUntil(lambda: len(transport.commands) >= 7, timeout=1000)
        assert transport.commands[-4:] == [
            b"AT+START",
            b"AT+STOP",
            b"AT+LIVESTREAM=CDC",
            b"AT+LIVESTREAM?",
        ]
    finally:
        controller.disconnect_device()


def test_worker_failure_clears_session_and_reports_disconnected(qtbot) -> None:
    controller = AppController(FailingReadTransport)
    connection_states: list[tuple[bool, str]] = []
    errors: list[str] = []
    controller.connection_changed.connect(
        lambda connected, device: connection_states.append((connected, device))
    )
    controller.error_raised.connect(errors.append)

    controller.connect_device("FAKE")

    qtbot.waitUntil(lambda: len(connection_states) >= 2, timeout=2000)
    assert connection_states == [(True, "FAKE"), (False, "")]
    assert errors == ["device disconnected"]
    assert not controller.is_running


def test_gateway_commands_are_routed_only_to_selected_node(qtbot) -> None:
    first = RecordingIdleTransport()
    second = RecordingIdleTransport()
    controller = AppController(RecordingIdleTransport)
    controller.accept_gateway_client(
        AcceptedGatewayClient("wifi-1", "peer-1", first)  # type: ignore[arg-type]
    )
    controller.accept_gateway_client(
        AcceptedGatewayClient("wifi-2", "peer-2", second)  # type: ignore[arg-type]
    )
    try:
        qtbot.waitUntil(lambda: len(second.commands) >= 3, timeout=1000)
        controller.send_command_to("wifi-1", "AT+STOP")
        qtbot.waitUntil(lambda: b"AT+STOP" in first.commands, timeout=1000)

        assert b"AT+STOP" not in second.commands
    finally:
        controller.disconnect_device()


class RecordingListener:
    def __init__(self) -> None:
        self.started: tuple[str, int] | None = None
        self.is_closed = False
        self.released: list[str] = []

    def start(self, local_ipv4: str, tcp_port: int) -> None:
        self.started = (local_ipv4, tcp_port)

    def accept(self, timeout_s: float):
        return None

    def release(self, connection_id: str) -> None:
        self.released.append(connection_id)

    def close(self) -> None:
        self.is_closed = True


class RecordingWakeService:
    def __init__(self) -> None:
        self.is_started = False
        self.is_stopped = False

    def start(self) -> None:
        self.is_started = True

    def stop(self) -> None:
        self.is_stopped = True


def test_wifi_server_starts_listener_and_udp_wake_without_a_client(qtbot) -> None:
    listener = RecordingListener()
    wake = RecordingWakeService()
    controller = AppController(
        RecordingIdleTransport,
        gateway_listener_factory=lambda: listener,
        wake_service_factory=lambda _config: wake,
    )
    config = WifiServerConfig(
        local_ipv4="192.168.43.100",
        netmask="255.255.255.0",
        expected_pc_ipv4="192.168.43.100",
    )

    controller.start_wifi_server(config)
    qtbot.waitUntil(lambda: controller.is_wifi_server_running, timeout=1000)
    controller.stop_wifi_server()

    assert listener.started == ("192.168.43.100", 54321)
    assert listener.is_closed is True
    assert wake.is_started is True
    assert wake.is_stopped is True


def test_wifi_listener_blocks_cdc_and_returns_to_listening_after_client_loss(
    qtbot,
) -> None:
    listener = RecordingListener()
    wake = RecordingWakeService()
    cdc = RecordingIdleTransport()
    controller = AppController(
        lambda: cdc,
        gateway_listener_factory=lambda: listener,
        wake_service_factory=lambda _config: wake,
    )
    config = WifiServerConfig(
        local_ipv4="192.168.43.100",
        netmask="255.255.255.0",
        expected_pc_ipv4="192.168.43.100",
    )
    server_states: list[tuple[bool, str]] = []
    errors: list[str] = []
    controller.wifi_server_changed.connect(
        lambda running, label: server_states.append((running, label))
    )
    controller.error_raised.connect(errors.append)

    controller.start_wifi_server(config)
    qtbot.waitUntil(lambda: controller.is_wifi_server_running, timeout=1000)
    controller.connect_device("FAKE")
    assert cdc.is_closed is False
    assert errors == ["stop the Wi-Fi listener before opening CDC"]

    gateway = FailingReadTransport()
    controller.accept_gateway_client(
        AcceptedGatewayClient("wifi-1", "peer-1", gateway)  # type: ignore[arg-type]
    )
    qtbot.waitUntil(lambda: "wifi-1" in listener.released, timeout=2000)
    qtbot.waitUntil(
        lambda: server_states[-1] == (True, "LISTENING 192.168.43.100:54321"),
        timeout=2000,
    )
    controller.stop_wifi_server()


def test_remove_offline_wifi_node_keeps_listener_and_live_session(qtbot) -> None:
    listener = RecordingListener()
    wake = RecordingWakeService()
    controller = AppController(
        RecordingIdleTransport,
        gateway_listener_factory=lambda: listener,
        wake_service_factory=lambda _config: wake,
    )
    config = WifiServerConfig(
        local_ipv4="192.168.43.100",
        netmask="255.255.255.0",
        expected_pc_ipv4="192.168.43.100",
    )
    summaries: list[list[NodeSummary]] = []
    controller.nodes_changed.connect(summaries.append)

    controller.start_wifi_server(config)
    controller.accept_gateway_client(
        AcceptedGatewayClient(
            "wifi-old", "peer-old", FailingReadTransport()  # type: ignore[arg-type]
        )
    )
    controller.accept_gateway_client(
        AcceptedGatewayClient(
            "wifi-live", "peer-live", RecordingIdleTransport()  # type: ignore[arg-type]
        )
    )
    try:
        qtbot.waitUntil(
            lambda: any(
                node.node_id == "wifi-old"
                and node.connection_state is ConnectionState.RECONNECTING
                for node in summaries[-1]
            ),
            timeout=2000,
        )

        controller.remove_offline_node("wifi-old")

        assert controller.is_wifi_server_running
        assert "wifi-live" in controller._sessions
        assert [node.node_id for node in summaries[-1]] == ["wifi-live"]
    finally:
        controller.disconnect_device()


def test_remove_offline_wifi_node_rejects_active_node(qtbot) -> None:
    controller = AppController(RecordingIdleTransport)
    errors: list[str] = []
    controller.error_raised.connect(errors.append)
    controller.accept_gateway_client(
        AcceptedGatewayClient(
            "wifi-live", "peer-live", RecordingIdleTransport()  # type: ignore[arg-type]
        )
    )
    try:
        controller.remove_offline_node("wifi-live")

        assert "wifi-live" in controller._sessions
        assert errors == ["cannot remove a connected device"]
    finally:
        controller.disconnect_device()


def test_rejected_gateway_releases_listener_capacity(qtbot) -> None:
    listener = RecordingListener()
    controller = AppController(
        RecordingIdleTransport,
        gateway_listener_factory=lambda: listener,
    )
    for node_number in range(16):
        controller.accept_gateway_client(
            AcceptedGatewayClient(
                f"wifi-{node_number}",
                f"peer-{node_number}",
                RecordingIdleTransport(),  # type: ignore[arg-type]
            )
        )
    rejected = RecordingIdleTransport()
    controller._gateway_listener = listener  # exercise listener bookkeeping path
    controller.accept_gateway_client(
        AcceptedGatewayClient("wifi-17", "peer-17", rejected)  # type: ignore[arg-type]
    )
    try:
        assert rejected.is_closed is True
        assert listener.released == ["wifi-17"]
    finally:
        controller._gateway_listener = None
        controller.disconnect_device()


def test_client_queued_by_stopped_listener_is_discarded() -> None:
    old_listener = RecordingListener()
    transport = RecordingIdleTransport()
    controller = AppController(RecordingIdleTransport)

    controller._accept_gateway_envelope(
        (
            old_listener,
            AcceptedGatewayClient("wifi-stale", "peer-stale", transport),  # type: ignore[arg-type]
        )
    )

    assert transport.is_closed is True
    assert old_listener.released == ["wifi-stale"]
    assert controller.is_running is False


def test_app_controller_accepts_sixteen_gateways_and_rejects_seventeenth(qtbot) -> None:
    controller = AppController(RecordingIdleTransport)
    transports = [RecordingIdleTransport() for _node_number in range(17)]
    errors: list[str] = []
    node_counts: list[int] = []
    controller.error_raised.connect(errors.append)
    controller.nodes_changed.connect(lambda nodes: node_counts.append(len(nodes)))
    try:
        for node_number, transport in enumerate(transports, start=1):
            controller.accept_gateway_client(
                AcceptedGatewayClient(
                    f"wifi-{node_number}",
                    f"peer-{node_number}",
                    transport,  # type: ignore[arg-type]
                )
            )
        qtbot.waitUntil(lambda: max(node_counts, default=0) == 16, timeout=3000)

        assert any("maximum active node count" in error for error in errors)
        assert transports[-1].is_closed is True
    finally:
        controller.disconnect_device()


def test_global_recording_writes_separate_uuid_node_files(qtbot, tmp_path) -> None:
    first_uuid = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
    second_uuid = uuid.UUID("00112233-4455-6677-8899-aabbccddeeff")
    first = QueueTransport()
    second = QueueTransport()
    summaries = []
    controller = AppController(RecordingIdleTransport)
    controller.nodes_changed.connect(lambda nodes: summaries.append(nodes))
    controller.accept_gateway_client(
        AcceptedGatewayClient("wifi-1", "peer-1", first)  # type: ignore[arg-type]
    )
    controller.accept_gateway_client(
        AcceptedGatewayClient("wifi-2", "peer-2", second)  # type: ignore[arg-type]
    )
    try:
        first.chunks.put(encode_jy_frame(first_uuid))
        second.chunks.put(encode_jy_frame(second_uuid))
        qtbot.waitUntil(
            lambda: any(
                len(nodes) == 2 and all(node.device_uuid for node in nodes)
                for nodes in summaries
            ),
            timeout=2000,
        )
        controller.set_recording(True, path=tmp_path)
        first.chunks.put(encode_jy_frame(first_uuid, sequence=2))
        second.chunks.put(encode_jy_frame(second_uuid, sequence=2))
        qtbot.waitUntil(lambda: len(list(tmp_path.glob("*/segment-001.sdf1"))) == 2)
        controller.set_recording(False)

        recordings = list(tmp_path.glob("*/segment-001.sdf1"))
        assert len(recordings) == 2
        assert all(recording.stat().st_size > 0 for recording in recordings)
    finally:
        controller.disconnect_device()


def test_wifi_reconnect_creates_next_recording_segment(qtbot, tmp_path) -> None:
    device_uuid = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
    first = QueueTransport()
    controller = AppController(RecordingIdleTransport)
    summaries = []
    controller.nodes_changed.connect(lambda nodes: summaries.append(nodes))
    controller.accept_gateway_client(
        AcceptedGatewayClient("wifi-1", "peer-1", first)  # type: ignore[arg-type]
    )
    try:
        first.chunks.put(encode_jy_frame(device_uuid))
        qtbot.waitUntil(
            lambda: any(nodes and nodes[0].device_uuid == device_uuid for nodes in summaries),
            timeout=2000,
        )
        controller.set_recording(True, path=tmp_path)
        first.chunks.put(encode_jy_frame(device_uuid, sequence=2))
        first.chunks.put(OSError("hotspot lost"))
        qtbot.waitUntil(
            lambda: any(
                nodes and nodes[0].connection_state.value == "reconnecting"
                for nodes in summaries
            ),
            timeout=2000,
        )

        second = QueueTransport()
        controller.accept_gateway_client(
            AcceptedGatewayClient("wifi-2", "peer-2", second)  # type: ignore[arg-type]
        )
        second.chunks.put(encode_jy_frame(device_uuid, sequence=3))
        qtbot.waitUntil(
            lambda: len(list(tmp_path.glob("*/segment-*.sdf1"))) == 2,
            timeout=2000,
        )
        second.chunks.put(encode_jy_frame(device_uuid, sequence=4))
        controller.set_recording(False)

        names = sorted(path.name for path in tmp_path.glob("*/segment-*.sdf1"))
        assert names == ["segment-001.sdf1", "segment-002.sdf1"]
        second_segment = next(tmp_path.glob("*/segment-002.sdf1"))
        assert second_segment.read_bytes().startswith(
            encode_jy_frame(device_uuid, sequence=3)
        )
    finally:
        controller.disconnect_device()


def test_manual_archive_export_is_saved_separately(qtbot, tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    device_uuid = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
    transport = QueueTransport()
    controller = AppController(RecordingIdleTransport)
    controller.accept_gateway_client(
        AcceptedGatewayClient("wifi-1", "peer-1", transport)  # type: ignore[arg-type]
    )
    try:
        transport.chunks.put(encode_jy_frame(device_uuid))
        qtbot.waitUntil(lambda: controller.selected_node_id == "wifi-1")
        qtbot.waitUntil(lambda: b"AT+UUID?" in transport.commands)
        qtbot.wait(100)
        controller.send_command("AT+EXPORT=UART")
        qtbot.waitUntil(lambda: b"AT+EXPORT=UART" in transport.commands)
        archive_frame = encode_jy_frame(device_uuid, sequence=2, flags=0x8000)
        transport.chunks.put(archive_frame)
        transport.chunks.put(
            encode_cli_frame("EXPORT_END:CHUNKS=1,FRAMES=1\r\n", sequence=3)
        )
        qtbot.waitUntil(
            lambda: len(list((tmp_path / "host" / "exports").rglob("*.sdf1"))) == 1,
            timeout=2000,
        )
        qtbot.wait(100)

        export_path = next((tmp_path / "host" / "exports").rglob("*.sdf1"))
        assert export_path.read_bytes() == archive_frame
    finally:
        controller.disconnect_device()


def test_second_archive_waits_for_its_own_terminal_event(qtbot, tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    device_uuid = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
    transport = QueueTransport()
    controller = AppController(RecordingIdleTransport)
    controller.accept_gateway_client(
        AcceptedGatewayClient("wifi-1", "peer-1", transport)  # type: ignore[arg-type]
    )
    try:
        transport.chunks.put(encode_jy_frame(device_uuid))
        qtbot.waitUntil(
            lambda: controller._session_index.summary("wifi-1").device_uuid
            == device_uuid,
            timeout=2000,
        )
        qtbot.wait(100)
        controller.send_command("AT+EXPORT=UART")
        transport.chunks.put(encode_cli_frame("EXPORT_EMPTY\r\n", sequence=2))
        qtbot.waitUntil(
            lambda: controller._sessions["wifi-1"].archive_recorder is None,
            timeout=2000,
        )

        controller.send_command("AT+EXPORT=UART")
        qtbot.wait(100)

        assert controller._sessions["wifi-1"].archive_recorder is not None
        assert len(list((tmp_path / "host" / "exports").rglob("*.sdf1"))) == 2
    finally:
        controller.disconnect_device()


def test_cancel_archive_finishes_after_stop_state_ack(
    qtbot, tmp_path, monkeypatch
) -> None:
    from test_archive_library import DEVICE_UUID

    monkeypatch.chdir(tmp_path)
    transport = QueueTransport()
    controller = AppController(lambda: transport)
    finished: list[tuple] = []
    controller.export_finished.connect(lambda *args: finished.append(args))
    controller.accept_gateway_client(
        AcceptedGatewayClient("wifi-1", "peer-1", transport)  # type: ignore[arg-type]
    )
    try:
        session = controller._sessions["wifi-1"]
        controller._session_index.bind_identity("wifi-1", DEVICE_UUID)
        session.store.update_control_state(
            FirmwareControlState(
                acquisition_state="IDLE",
                device_uuid=DEVICE_UUID,
                sd_ready=True,
                sd_used=64,
                sd_capacity=1024,
            )
        )

        controller.start_export_for("wifi-1")
        qtbot.waitUntil(lambda: b"AT+EXPORT=UART" in transport.commands)
        controller.cancel_export_for("wifi-1")
        qtbot.waitUntil(
            lambda: b"AT+STOP" in transport.commands
            and transport.commands.count(b"AT+STATE?") >= 2
        )
        assert session.archive_recorder is not None

        transport.chunks.put(encode_cli_frame("OK\r\n", sequence=2))
        transport.chunks.put(
            encode_cli_frame(
                "+STATE:IDLE\r\n"
                "+EXPORT:TARGET=NONE,CHUNK=0,FRAME=0\r\n"
                "+SD:USED=64,CAPACITY=1024,PENDING_FRAMES=0,"
                "RETAINED_CHUNKS=1,RETAINED_FRAMES=2,"
                "OVERWRITTEN_CHUNKS=0,OVERWRITTEN_FRAMES=0,"
                "READY=1,FORMAT_REQUIRED=0\r\n"
                "OK\r\n",
                sequence=3,
            )
        )
        qtbot.waitUntil(lambda: session.archive_recorder is None, timeout=2000)

        assert finished and finished[0][1] == "ABORTED"
    finally:
        controller.disconnect_device()


def test_clear_sd_queues_confirmed_command_only_when_idle(qtbot) -> None:
    transport = RecordingIdleTransport()
    controller = AppController(lambda: transport)
    controller.accept_gateway_client(
        AcceptedGatewayClient("wifi-1", "peer-1", transport)  # type: ignore[arg-type]
    )
    try:
        session = controller._sessions["wifi-1"]
        session.store.update_control_state(
            FirmwareControlState(acquisition_state="IDLE", sd_ready=True)
        )

        controller.clear_sd_for("wifi-1")
        qtbot.waitUntil(lambda: b"AT+SDCLEAR=CONFIRM" in transport.commands)

        session.store.update_control_state(
            FirmwareControlState(acquisition_state="ACQUIRE", sd_ready=True)
        )
        command_count = transport.commands.count(b"AT+SDCLEAR=CONFIRM")
        controller.clear_sd_for("wifi-1")
        qtbot.wait(100)

        assert transport.commands.count(b"AT+SDCLEAR=CONFIRM") == command_count
    finally:
        controller.disconnect_device()


def test_disconnect_with_slow_transport_stays_within_stop_timeout(qtbot) -> None:
    controller = AppController(SlowCloseTransport)
    controller.connect_device("FAKE")
    qtbot.waitUntil(lambda: controller.is_running, timeout=1000)

    started = time.perf_counter()
    controller.disconnect_device()
    elapsed = time.perf_counter() - started

    # UI-21: a slow transport close must not block beyond the thread-stop budget;
    # staying within it means no lifecycle refactor is warranted yet.
    assert elapsed < 3.0
    assert not controller.is_running


def test_window_minimum_fits_small_workspaces(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.minimumWidth() <= 960
    assert window.minimumHeight() <= 540

    sensor_host_app._fit_window_to_available_geometry(window)
    assert window.width() >= window.minimumWidth()
    assert window.height() >= window.minimumHeight()


def test_offline_node_does_not_steal_commands_end_to_end(qtbot) -> None:
    online = RecordingIdleTransport()
    offline = FailingReadTransport()
    controller = AppController(RecordingIdleTransport)
    window = MainWindow()
    qtbot.addWidget(window)

    sensor_host_app._wire_acquisition_controls(window, controller)
    controller.connection_changed.connect(
        lambda connected, _device: window.set_connected(connected)
    )
    controller.nodes_changed.connect(window.set_nodes)
    controller.selected_node_changed.connect(window.node_sidebar.set_selected_node)
    window.node_sidebar.node_selected.connect(controller.select_node)

    controller.accept_gateway_client(
        AcceptedGatewayClient("wifi-a", "peer-a", offline)  # type: ignore[arg-type]
    )
    controller.accept_gateway_client(
        AcceptedGatewayClient("wifi-b", "peer-b", online)  # type: ignore[arg-type]
    )
    try:
        # wifi-a drops; the target must fall back to online wifi-b and the
        # sidebar highlight must follow through the same write-back path.
        qtbot.waitUntil(lambda: controller.selected_node_id == "wifi-b", timeout=2000)
        qtbot.waitUntil(
            lambda: window.node_sidebar.selected_node_id == "wifi-b", timeout=1000
        )
        qtbot.waitUntil(lambda: len(online.commands) >= 3, timeout=1000)

        # Clicking the offline wifi-a row must not retarget any command.
        window.node_sidebar.node_list.setCurrentRow(0)
        assert window.node_sidebar.selected_node_id == "wifi-b"
        assert controller.selected_node_id == "wifi-b"

        window.start_button.click()
        window.stop_button.click()
        controller.send_command("AT+PING")
        qtbot.waitUntil(lambda: b"AT+PING" in online.commands, timeout=1000)

        assert b"AT+START" in online.commands
        assert b"AT+STOP" in online.commands
        assert b"AT+START" not in offline.commands
        assert b"AT+PING" not in offline.commands
    finally:
        controller.disconnect_device()


def test_inactive_tcp_session_releases_listener_capacity(qtbot, monkeypatch):
    import socket
    from sensor_host.transport import GatewayListener, gateway
    monkeypatch.setattr(gateway, "_GATEWAY_INACTIVITY_SECONDS", 0.1)
    listener = GatewayListener(maximum_clients=1)
    listener.start("127.0.0.1", 0)
    controller = AppController(RecordingIdleTransport)
    controller._gateway_listener = listener
    client = socket.create_connection(("127.0.0.1", listener.bound_port))
    replacement = None
    accepted = None
    try:
        old = listener.accept(0.5)
        controller.accept_gateway_client(old)
        qtbot.waitUntil(lambda: not controller._sessions, timeout=2000)
        assert not listener._active_connections
        replacement = socket.create_connection(("127.0.0.1", listener.bound_port))
        accepted = listener.accept(0.5)
        assert accepted is not None
    finally:
        if accepted is not None:
            accepted.transport.close()
        if replacement is not None:
            replacement.close()
        client.close()
        controller.disconnect_device()


def test_clear_action_preserves_other_nodes_and_recording_while_paused(qtbot, tmp_path):
    from sensor_host.protocol import IisSample
    controller = AppController(RecordingIdleTransport)
    window = MainWindow()
    qtbot.addWidget(window)
    sensor_host_app._wire_acquisition_controls(window, controller)
    try:
        for name in ("wifi-one", "wifi-two"):
            controller.accept_gateway_client(AcceptedGatewayClient(name, name, RecordingIdleTransport()))
        controller.select_node("wifi-one")
        for session in controller._sessions.values():
            controller._session_index.bind_identity(session.node_id, uuid.uuid4())
            session.store.append_iis((IisSample(1000, (1, 2, 3), (0.1, 0.2, 0.3)),))
        controller.set_recording(True, tmp_path / "recording")
        recorders = [session.recorder for session in controller._sessions.values()]
        controller.set_display_paused(True)
        window.set_display_paused(True)
        window.vibration_view.clear_button.click()
        assert controller._sessions["wifi-one"].store.snapshot(10, 100).time_s.size == 0
        assert controller._sessions["wifi-two"].store.snapshot(10, 100).time_s.size == 1
        assert controller._recording_active
        assert recorders == [session.recorder for session in controller._sessions.values()]
    finally:
        controller.disconnect_device()


def test_immediate_reconnect_ignores_previous_session_callbacks(qtbot):
    controller = AppController(RecordingIdleTransport)
    try:
        controller.connect_device("COM6")
        previous = controller._selected_session()
        # Queue the failure and finished callbacks without processing GUI events.
        previous.worker.failed.emit("old session failure")
        controller.disconnect_device()
        controller.connect_device("COM6")
        current = controller._selected_session()
        assert current is not previous
        # Avoid destroying a running QThread in the regression's failing case.
        current.stop_event.set()
        current.thread.quit()
        assert current.thread.wait(3000)
        errors = []
        controller.error_raised.connect(errors.append)
        previous.worker.failed.emit("late old failure")
        assert current.failure is None
        assert errors == []
        previous.thread.finished.emit()
        assert controller._selected_session() is current
    finally:
        controller.disconnect_device()


def test_disconnect_emits_display_clear_requested(qtbot) -> None:
    controller = AppController(RecordingIdleTransport)
    controller.connect_device("FAKE")
    try:
        qtbot.waitUntil(lambda: controller.is_running, timeout=1000)
        with qtbot.waitSignal(controller.display_clear_requested, timeout=2000):
            controller.disconnect_device()
    finally:
        controller.disconnect_device()


def test_last_gateway_death_clears_display_while_listener_stays_up(qtbot) -> None:
    controller = AppController(RecordingIdleTransport)
    clears: list[int] = []
    controller.display_clear_requested.connect(lambda: clears.append(1))
    controller.accept_gateway_client(
        AcceptedGatewayClient("wifi-1", "peer-1", FailingReadTransport())  # type: ignore[arg-type]
    )
    try:
        qtbot.waitUntil(lambda: bool(clears), timeout=2000)
        assert not controller._sessions
    finally:
        controller.disconnect_device()


def test_export_then_library_open_replays_end_to_end(qtbot, tmp_path) -> None:
    from test_archive_library import DEVICE_UUID, encode_iis_frame

    window = MainWindow()
    qtbot.addWidget(window)
    transport = QueueTransport()
    controller = AppController(lambda: transport)
    sensor_host_app._wire_archive_and_playback(window, controller)
    controller.accept_gateway_client(
        AcceptedGatewayClient("wifi-1", "peer-1", transport)  # type: ignore[arg-type]
    )
    try:
        transport.chunks.put(encode_jy_frame(DEVICE_UUID, sequence=1))
        qtbot.waitUntil(
            lambda: controller._session_index.summary("wifi-1").device_uuid
            is not None,
            timeout=2000,
        )
        transport.chunks.put(
            encode_cli_frame(
                "+STATE:IDLE\r\n"
                "+SD:USED=64,CAPACITY=1024,PENDING_FRAMES=0,RETAINED_CHUNKS=1,"
                "RETAINED_FRAMES=2,OVERWRITTEN_CHUNKS=0,OVERWRITTEN_FRAMES=0,"
                "READY=1,FORMAT_REQUIRED=0\r\n"
                "OK\r\n",
                sequence=2,
            )
        )
        qtbot.waitUntil(
            lambda: controller.sd_records()
            and controller.sd_records()[0].sd_ready is True,
            timeout=2000,
        )

        controller.start_export_for("wifi-1")
        qtbot.waitUntil(
            lambda: b"AT+EXPORT=UART" in transport.commands, timeout=2000
        )
        transport.chunks.put(
            encode_iis_frame(3, 1_000_000, flags=0x8000)
        )
        transport.chunks.put(
            encode_iis_frame(4, 2_000_000, flags=0x8000)
        )
        transport.chunks.put(
            encode_cli_frame("EXPORT_END:CHUNKS=1,FRAMES=2\r\n", sequence=5)
        )
        qtbot.waitUntil(
            lambda: controller._sessions["wifi-1"].archive_recorder is None,
            timeout=3000,
        )
        qtbot.waitUntil(
            lambda: window.archive_view.library_table.rowCount() == 1,
            timeout=2000,
        )

        window.archive_view.library_table.selectRow(0)
        window.archive_view.open_button.click()
        qtbot.waitUntil(lambda: window._playback_active, timeout=5000)
        assert window.playback_bar.file_label.text().endswith(".sdf1")

        window.playback_bar.play_button.click()
        qtbot.waitUntil(
            lambda: window.vibration_view.rate_label.text()
            != "0 samples/s · 0 visible points",
            timeout=3000,
        )
        window.playback_bar.stop_button.click()
        qtbot.waitUntil(lambda: not window._playback_active, timeout=2000)
    finally:
        controller.disconnect_device()


def test_export_rejected_while_acquiring(qtbot) -> None:
    from test_archive_library import DEVICE_UUID

    transport = QueueTransport()
    controller = AppController(lambda: transport)
    errors: list[str] = []
    controller.error_raised.connect(errors.append)
    controller.accept_gateway_client(
        AcceptedGatewayClient("wifi-1", "peer-1", transport)  # type: ignore[arg-type]
    )
    try:
        transport.chunks.put(encode_jy_frame(DEVICE_UUID, sequence=1))
        qtbot.waitUntil(
            lambda: controller._session_index.summary("wifi-1").device_uuid
            is not None,
            timeout=2000,
        )
        transport.chunks.put(
            encode_cli_frame(
                "+STATE:ACQUIRE\r\n"
                "+SD:USED=64,CAPACITY=1024,PENDING_FRAMES=0,RETAINED_CHUNKS=1,"
                "RETAINED_FRAMES=2,OVERWRITTEN_CHUNKS=0,OVERWRITTEN_FRAMES=0,"
                "READY=1,FORMAT_REQUIRED=0\r\n"
                "OK\r\n",
                sequence=2,
            )
        )
        qtbot.waitUntil(
            lambda: controller.sd_records()
            and controller.sd_records()[0].sd_ready is True,
            timeout=2000,
        )

        controller.start_export_for("wifi-1")
        qtbot.wait(100)

        assert controller._sessions["wifi-1"].archive_recorder is None
        assert b"AT+EXPORT=UART" not in transport.commands
        assert any("stop acquisition" in message for message in errors)
    finally:
        controller.disconnect_device()


def test_stalled_export_watchdog_detaches_recorder(qtbot) -> None:
    from test_archive_library import DEVICE_UUID

    transport = QueueTransport()
    controller = AppController(lambda: transport)
    errors: list[str] = []
    controller.error_raised.connect(errors.append)
    finished: list[tuple] = []
    controller.export_finished.connect(lambda *args: finished.append(args))
    controller.accept_gateway_client(
        AcceptedGatewayClient("wifi-1", "peer-1", transport)  # type: ignore[arg-type]
    )
    try:
        transport.chunks.put(encode_jy_frame(DEVICE_UUID, sequence=1))
        qtbot.waitUntil(
            lambda: controller._session_index.summary("wifi-1").device_uuid
            is not None,
            timeout=2000,
        )
        session = controller._sessions["wifi-1"]
        controller._start_archive_recording(session)
        assert session.archive_recorder is not None
        session.archive_started_s -= 100.0

        controller._watchdog_stalled_export(session)

        assert session.archive_recorder is None
        assert finished and finished[0][1] == "STALLED"
        assert any("export stalled" in message for message in errors)
    finally:
        controller.disconnect_device()


def test_zero_byte_abort_triggers_one_automatic_retry(qtbot) -> None:
    from test_archive_library import DEVICE_UUID

    transport = QueueTransport()
    controller = AppController(lambda: transport)
    errors: list[str] = []
    controller.error_raised.connect(errors.append)
    controller.accept_gateway_client(
        AcceptedGatewayClient("wifi-1", "peer-1", transport)  # type: ignore[arg-type]
    )
    try:
        transport.chunks.put(encode_jy_frame(DEVICE_UUID, sequence=1))
        qtbot.waitUntil(
            lambda: controller._session_index.summary("wifi-1").device_uuid
            is not None,
            timeout=2000,
        )
        transport.chunks.put(
            encode_cli_frame(
                "+STATE:IDLE\r\n"
                "+SD:USED=64,CAPACITY=1024,PENDING_FRAMES=0,RETAINED_CHUNKS=1,"
                "RETAINED_FRAMES=2,OVERWRITTEN_CHUNKS=0,OVERWRITTEN_FRAMES=0,"
                "READY=1,FORMAT_REQUIRED=0\r\n"
                "OK\r\n",
                sequence=2,
            )
        )
        qtbot.waitUntil(
            lambda: controller.sd_records()
            and controller.sd_records()[0].sd_ready is True,
            timeout=2000,
        )
        controller.start_export_for("wifi-1")
        qtbot.waitUntil(
            lambda: transport.commands.count(b"AT+EXPORT=UART") == 1,
            timeout=2000,
        )
        session = controller._sessions["wifi-1"]

        transport.chunks.put(encode_cli_frame("EXPORT_ABORTED\r\n", sequence=3))
        qtbot.waitUntil(
            lambda: transport.commands.count(b"AT+EXPORT=UART") == 2,
            timeout=3000,
        )
        assert session.archive_recorder is not None
        assert any("automatic retry" in message for message in errors)

        transport.chunks.put(encode_cli_frame("EXPORT_ABORTED\r\n", sequence=4))
        qtbot.waitUntil(lambda: session.archive_recorder is None, timeout=3000)
        qtbot.wait(150)
        assert transport.commands.count(b"AT+EXPORT=UART") == 2
        assert any("retry after STOP" in message for message in errors)
    finally:
        controller.disconnect_device()


def test_open_export_enters_playback_and_stop_returns_to_live(qtbot, tmp_path) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    controller = AppController(RecordingIdleTransport)
    sensor_host_app._wire_archive_and_playback(window, controller)
    try:
        path = write_archive(tmp_path / "export.sdf1")
        window.archive_view.open_requested.emit(path)
        qtbot.waitUntil(lambda: window._playback_active, timeout=5000)
        assert not window.playback_bar.isHidden()
        assert window.tabs.currentWidget() is window.live_tab
        assert window.playback_bar.file_label.text() == "export.sdf1"

        window.playback_bar.play_button.click()
        qtbot.waitUntil(
            lambda: window.vibration_view.rate_label.text()
            != "0 samples/s · 0 visible points",
            timeout=3000,
        )

        window.playback_bar.stop_button.click()
        qtbot.waitUntil(lambda: not window._playback_active, timeout=2000)
        assert window.playback_bar.isHidden()
        assert window.vibration_view.rate_label.text() == (
            "0 samples/s · 0 visible points"
        )
    finally:
        controller.disconnect_device()
