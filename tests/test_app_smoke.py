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
