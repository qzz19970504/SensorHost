"""Application composition root for the PyQt sensor host."""

from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from sensor_host.presentation import (
    AppController,
    MainWindow,
    dark_stylesheet,
    load_application_fonts,
)
from sensor_host.transport import CdcSerialTransport


def main() -> int:
    """Create, show, and run the sensor host application."""
    application = QApplication(sys.argv)
    application.setApplicationName("STM32 Sensor Host")
    load_application_fonts()
    application.setStyleSheet(dark_stylesheet())
    window = MainWindow()
    controller = AppController(CdcSerialTransport)

    def refresh_devices() -> None:
        discovery = CdcSerialTransport()
        try:
            devices = discovery.discover()
        except (OSError, RuntimeError) as error:
            window.console_view.append_error(str(error))
            return
        window.set_devices([(device.device_id, device.label) for device in devices])

    window.connect_requested.connect(controller.connect_device)
    window.disconnect_requested.connect(controller.disconnect_device)
    window.pause_toggled.connect(controller.set_display_paused)
    window.record_toggled.connect(controller.set_recording)
    window.watermark_requested.connect(controller.set_watermark)
    window.window_combo.currentIndexChanged.connect(
        lambda: controller.set_window_seconds(float(window.window_combo.currentData()))
    )
    window.refresh_requested.connect(refresh_devices)
    window.console_view.command_submitted.connect(controller.send_command)
    controller.snapshot_ready.connect(window.update_snapshot)
    controller.health_ready.connect(window.update_health)
    controller.cli_response.connect(window.console_view.append_response)
    controller.error_raised.connect(window.console_view.append_error)
    controller.connection_changed.connect(lambda connected, _device: window.set_connected(connected))
    application.aboutToQuit.connect(controller.disconnect_device)
    refresh_devices()
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
