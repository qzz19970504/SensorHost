"""Application composition root for the PyQt sensor host."""

from __future__ import annotations

import os
import sys
import threading
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import QObject, QSettings, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from sensor_host.branding import APPLICATION_ICON_PATH, APPLICATION_NAME
from sensor_host.presentation import (
    AppController,
    MainWindow,
    OtaDialog,
    dark_stylesheet,
    load_application_fonts,
)
from sensor_host.presentation.playback_controller import PlaybackController
from sensor_host.storage import build_playback_index
from sensor_host.transport import CdcSerialTransport, FakeTransport, Transport
from sensor_host.presentation.connection_view import discover_ipv4_interfaces


SMOKE_TEST_ARGUMENT = "--smoke-test"
FAKE_ARGUMENT = "--fake"
OFFSCREEN_PLATFORM = "offscreen"


class _IndexBridge(QObject):
    """Deliver background playback-index results back to the GUI thread."""

    ready = pyqtSignal(object, object, str)


def _wire_acquisition_controls(
    window: MainWindow,
    controller: AppController,
) -> None:
    """Connect acquisition toolbar actions to the selected-node controller."""
    window.clear_requested.connect(controller.clear_display_samples)
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
    application.setApplicationName(APPLICATION_NAME)
    application.setWindowIcon(QIcon(str(APPLICATION_ICON_PATH)))
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


def _run_interactive(
    application: QApplication,
    *,
    transport_factory: Callable[[], Transport] = CdcSerialTransport,
    fake_mode: bool = False,
) -> int:
    """Wire transports and controllers, then run the interactive event loop."""
    settings = QSettings("OpenAI", "STM32SensorHost")
    window = MainWindow(settings=settings)
    controller = AppController(transport_factory, settings=settings)

    def refresh_devices() -> None:
        window.set_network_interfaces(discover_ipv4_interfaces())
        discovery = transport_factory()
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
    controller.snapshot_ready.connect(window.update_live_snapshot)
    controller.health_ready.connect(window.update_health)
    controller.cli_response.connect(window.console_view.append_response)
    controller.cli_response_from.connect(window.console_view.append_response_from)
    controller.selected_node_changed.connect(window.console_view.set_current_node)
    controller.error_raised.connect(window.console_view.append_error)
    controller.error_raised.connect(window.show_error)
    controller.connection_changed.connect(lambda connected, _device: window.set_connected(connected))
    controller.wifi_server_changed.connect(window.set_wifi_server_state)
    controller.nodes_changed.connect(window.set_nodes)
    controller.selected_node_changed.connect(window.node_sidebar.set_selected_node)
    controller.display_clear_requested.connect(window.clear_live_views)
    window.node_sidebar.node_selected.connect(controller.select_node)
    window.node_sidebar.alias_requested.connect(controller.set_alias)
    window.node_sidebar.remove_requested.connect(controller.remove_offline_node)
    _wire_archive_and_playback(window, controller)
    _wire_firmware(window, controller)
    application.aboutToQuit.connect(controller.disconnect_device)
    refresh_devices()
    if fake_mode:
        controller.connect_device(FakeTransport.DEVICE_ID)
    window.wifi_panel.restore_settings(settings)
    _fit_window_to_available_geometry(window)
    window.show()
    return application.exec()


def _wire_archive_and_playback(window: MainWindow, controller: AppController) -> None:
    """Connect the SD archive view, export flow and offline playback source."""
    playback = PlaybackController(
        window_seconds_provider=lambda: float(window.window_combo.currentData() or 10.0),
        parent=window,
    )
    bar = window.playback_bar
    bar.play_toggled.connect(
        lambda checked: playback.play() if checked else playback.pause()
    )
    bar.stop_requested.connect(playback.stop)
    bar.stop_requested.connect(window.exit_playback)
    bar.seek_requested.connect(playback.seek)
    bar.speed_changed.connect(playback.set_speed)
    playback.snapshot_ready.connect(window.update_snapshot)
    playback.state_changed.connect(bar.set_state)

    window.archive_view.export_requested.connect(controller.start_export_for)
    window.archive_view.cancel_requested.connect(controller.cancel_export_for)
    window.archive_view.clear_requested.connect(controller.clear_sd_for)
    window.archive_view.refresh_requested.connect(controller.request_status_all)
    controller.export_finished.connect(window.archive_view.on_export_finished)

    index_bridge = _IndexBridge()

    def finish(index_path: object, index: object, error: str) -> None:
        window.archive_view.set_open_busy(False)
        if index is None:
            window.show_error(f"indexing {Path(index_path).name} failed: {error}")
            return
        playback.load(Path(index_path), index)  # type: ignore[arg-type]
        window.playback_bar.set_file_name(Path(index_path).name)
        window.clear_live_views()
        window.set_playback_active(True)

    index_bridge.ready.connect(finish)

    def open_for_playback(path: Path) -> None:
        window.archive_view.set_open_busy(True)

        def work() -> None:
            try:
                index = build_playback_index(path)
                error = ""
            except OSError as read_error:
                index = None
                error = str(read_error)
            index_bridge.ready.emit(path, index, error)

        threading.Thread(target=work, daemon=True, name="sdf1-index").start()

    window.archive_view.open_requested.connect(open_for_playback)
    window.archive_view.set_controller(controller)


def _wire_firmware(window: MainWindow, controller: AppController) -> OtaDialog:
    """Connect the FIRMWARE/OTA toolbar entry, dialog and controller signals."""
    dialog = OtaDialog(window)

    def open_dialog() -> None:
        dialog.set_node(controller.selected_node_id)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    window.firmware_requested.connect(open_dialog)
    controller.ota_availability.connect(window.set_firmware_available)
    dialog.upload_requested.connect(controller.start_ota_for)
    dialog.cancel_requested.connect(controller.cancel_ota_for)
    controller.ota_progress.connect(dialog.on_progress)
    controller.ota_staged.connect(dialog.on_staged)
    controller.ota_state.connect(dialog.on_state)
    return dialog


def main(argv: list[str] | None = None) -> int:
    """Run the interactive host or its deterministic packaging smoke mode."""
    arguments = list(sys.argv if argv is None else argv)
    is_smoke_test = SMOKE_TEST_ARGUMENT in arguments[1:]
    is_fake = FAKE_ARGUMENT in arguments[1:]
    if is_smoke_test:
        os.environ.setdefault("QT_QPA_PLATFORM", OFFSCREEN_PLATFORM)
        arguments = [
            argument
            for argument in arguments
            if argument not in {SMOKE_TEST_ARGUMENT, FAKE_ARGUMENT}
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
    return _run_interactive(
        application,
        transport_factory=FakeTransport if is_fake else CdcSerialTransport,
        fake_mode=is_fake,
    )


if __name__ == "__main__":
    raise SystemExit(main())
