"""Application composition root for the PyQt sensor host."""

from __future__ import annotations

import os
import sys

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication

from sensor_host.presentation import (
    AppController,
    MainWindow,
    dark_stylesheet,
    load_application_fonts,
)
from sensor_host.transport import CdcSerialTransport
from sensor_host.presentation.connection_view import discover_ipv4_interfaces


SMOKE_TEST_ARGUMENT = "--smoke-test"
OFFSCREEN_PLATFORM = "offscreen"


def _wire_acquisition_controls(
    window: MainWindow,
    controller: AppController,
) -> None:
    """Connect acquisition toolbar actions to the selected-node controller."""
    window.start_requested.connect(controller.start_acquisition)
    window.stop_requested.connect(controller.stop_acquisition)
    window.livestream_requested.connect(
        lambda target: _set_and_query_livestream(controller, target)
    )


def _set_and_query_livestream(
    controller: AppController,
    target: str,
) -> None:
    """Set a live target and request authoritative state for GUI synchronization."""
    controller.set_livestream(target)
    controller.request_livestream()


def _create_application(arguments: list[str]) -> QApplication:
    """Create or reuse the process QApplication and apply the host theme."""
    existing_application = QApplication.instance()
    application = (
        existing_application
        if isinstance(existing_application, QApplication)
        else QApplication(arguments)
    )
    application.setApplicationName("STM32 Sensor Host")
    load_application_fonts()
    application.setStyleSheet(dark_stylesheet())
    return application


def _fit_window_to_available_geometry(window: MainWindow) -> None:
    """Clamp the initial window size to the usable work area (UI-08)."""
    screen = QApplication.primaryScreen()
    if screen is None:
        return
    available = screen.availableGeometry()
    width = min(window.width(), max(available.width(), window.minimumWidth()))
    height = min(window.height(), max(available.height(), window.minimumHeight()))
    window.resize(width, height)


def _run_smoke_test(application: QApplication) -> int:
    """Construct and render one offscreen window without serial discovery."""
    window = MainWindow()
    window.show()
    application.processEvents()
    window.close()
    return 0


def _run_interactive(application: QApplication) -> int:
    """Wire transports and controllers, then run the interactive event loop."""
    window = MainWindow()
    settings = QSettings("OpenAI", "STM32SensorHost")
    controller = AppController(CdcSerialTransport, settings=settings)

    def refresh_devices() -> None:
        window.set_network_interfaces(discover_ipv4_interfaces())
        discovery = CdcSerialTransport()
        try:
            devices = discovery.discover()
        except (OSError, RuntimeError) as error:
            window.console_view.append_error(str(error))
            return
        window.set_devices([(device.device_id, device.label) for device in devices])

    window.connect_requested.connect(controller.connect_device)
    window.wifi_start_requested.connect(controller.start_wifi_server)
    window.disconnect_requested.connect(controller.disconnect_device)
    window.pause_toggled.connect(controller.set_display_paused)
    window.pause_toggled.connect(window.set_display_paused)
    window.record_toggled.connect(controller.set_recording)
    window.watermark_requested.connect(controller.set_watermark)
    _wire_acquisition_controls(window, controller)
    window.window_combo.currentIndexChanged.connect(
        lambda: controller.set_window_seconds(float(window.window_combo.currentData()))
    )
    window.refresh_requested.connect(refresh_devices)
    window.console_view.command_submitted.connect(controller.send_command)
    controller.snapshot_ready.connect(window.update_snapshot)
    controller.health_ready.connect(window.update_health)
    controller.cli_response.connect(window.console_view.append_response)
    controller.error_raised.connect(window.console_view.append_error)
    controller.error_raised.connect(window.show_error)
    controller.connection_changed.connect(lambda connected, _device: window.set_connected(connected))
    controller.wifi_server_changed.connect(window.set_wifi_server_state)
    controller.nodes_changed.connect(window.set_nodes)
    controller.selected_node_changed.connect(window.node_sidebar.set_selected_node)
    window.node_sidebar.node_selected.connect(controller.select_node)
    window.node_sidebar.alias_requested.connect(controller.set_alias)
    application.aboutToQuit.connect(controller.disconnect_device)
    refresh_devices()
    window.wifi_panel.restore_settings(settings)
    _fit_window_to_available_geometry(window)
    window.show()
    return application.exec()


def main(argv: list[str] | None = None) -> int:
    """Run the interactive host or its deterministic packaging smoke mode."""
    arguments = list(sys.argv if argv is None else argv)
    is_smoke_test = SMOKE_TEST_ARGUMENT in arguments[1:]
    if is_smoke_test:
        os.environ.setdefault("QT_QPA_PLATFORM", OFFSCREEN_PLATFORM)
        arguments = [
            argument for argument in arguments if argument != SMOKE_TEST_ARGUMENT
        ]
    existing_application = QApplication.instance()
    original_stylesheet = (
        existing_application.styleSheet()
        if isinstance(existing_application, QApplication)
        else None
    )
    application = _create_application(arguments)
    if is_smoke_test:
        try:
            return _run_smoke_test(application)
        finally:
            if original_stylesheet is not None:
                application.setStyleSheet(original_stylesheet)
                application.processEvents()
    return _run_interactive(application)


if __name__ == "__main__":
    raise SystemExit(main())
