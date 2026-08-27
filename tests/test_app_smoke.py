from sensor_host.presentation.app_controller import AppController


def test_app_controller_stops_worker_thread(qtbot, fake_transport_factory) -> None:
    controller = AppController(fake_transport_factory)

    controller.connect_device("FAKE")
    qtbot.waitUntil(lambda: controller.is_running, timeout=1000)
    controller.disconnect_device()

    qtbot.waitUntil(lambda: not controller.is_running, timeout=2000)
