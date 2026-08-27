from sensor_host.presentation.app_controller import AppController


class RecordingIdleTransport:
    def __init__(self) -> None:
        self.commands: list[bytes] = []

    def open(self, device_id: str) -> None:
        self.device_id = device_id

    def close(self) -> None:
        pass

    def read(self, max_bytes: int, timeout_s: float) -> bytes:
        return b""

    def write_control(self, command: bytes) -> None:
        self.commands.append(command)


class FailingReadTransport(RecordingIdleTransport):
    def read(self, max_bytes: int, timeout_s: float) -> bytes:
        raise OSError("device disconnected")


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
        qtbot.waitUntil(lambda: b"status" in transport.commands, timeout=1000)
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
