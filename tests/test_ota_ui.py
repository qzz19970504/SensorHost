"""UI smoke tests for the FIRMWARE/OTA entry and the OTA dialog."""

from __future__ import annotations

from PyQt6.QtWidgets import QMessageBox

from sensor_host import app as sensor_host_app
from sensor_host.ota.package import pack_ota
from sensor_host.presentation.app_controller import AppController
from sensor_host.presentation.main_window import MainWindow
from sensor_host.presentation.ota_dialog import OtaDialog
from sensor_host.transport import AcceptedGatewayClient


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

    def write_raw(self, data: bytes) -> None:
        self.commands.append(data)


def _package(tmp_path, size: int = 1200, version: str = "1.2.3"):
    image = bytes((index * 3 + 1) & 0xFF for index in range(size))
    path = tmp_path / "app.ota"
    path.write_bytes(pack_ota(image=image, app_version=version))
    return path


def test_main_window_exposes_disabled_firmware_button(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.firmware_button.text() == "FIRMWARE"
    assert window.firmware_button.isEnabled() is False


def test_firmware_enabled_for_wifi_node(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    controller = AppController(RecordingIdleTransport)
    sensor_host_app._wire_firmware(window, controller)
    controller.accept_gateway_client(
        AcceptedGatewayClient("wifi-1", "peer-1", RecordingIdleTransport())  # type: ignore[arg-type]
    )
    try:
        qtbot.waitUntil(lambda: window.firmware_button.isEnabled(), timeout=2000)
    finally:
        controller.disconnect_device()


def test_firmware_disabled_with_tooltip_for_cdc_node(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    controller = AppController(RecordingIdleTransport)
    sensor_host_app._wire_firmware(window, controller)
    controller.connect_device("FAKE")
    try:
        qtbot.waitUntil(
            lambda: controller.selected_node_id == "cdc:FAKE", timeout=2000
        )
        qtbot.wait(50)
        assert window.firmware_button.isEnabled() is False
        assert "UART" in window.firmware_button.toolTip()
    finally:
        controller.disconnect_device()


def test_dialog_shows_package_summary(qtbot, tmp_path) -> None:
    dialog = OtaDialog()
    qtbot.addWidget(dialog)
    dialog.set_node("wifi-1")
    path = _package(tmp_path)

    assert dialog.load_package_summary(str(path)) is True

    summary = dialog.summary_label.text()
    assert "VERSION 1.2.3" in summary
    assert "1,200 bytes" in summary
    assert "TARGET F407VE-JY-I3DWB" in summary
    assert dialog.start_button.isEnabled() is True


def test_dialog_rejects_bad_package(qtbot, tmp_path) -> None:
    dialog = OtaDialog()
    qtbot.addWidget(dialog)
    dialog.set_node("wifi-1")
    good = _package(tmp_path, size=600, version="1.0.0")
    bad = tmp_path / "bad.ota"
    bad.write_bytes(good.read_bytes()[:-1])

    assert dialog.load_package_summary(str(bad)) is False
    assert "包自检失败" in dialog.summary_label.text()
    assert dialog.start_button.isEnabled() is False


def test_dialog_start_emits_upload_request_and_arms_cancel(qtbot, tmp_path) -> None:
    dialog = OtaDialog()
    qtbot.addWidget(dialog)
    dialog.set_node("wifi-1")
    path = _package(tmp_path, version="1.0.0")
    dialog.load_package_summary(str(path))
    requests: list[tuple[str, str]] = []
    dialog.upload_requested.connect(lambda node, pkg: requests.append((node, pkg)))

    dialog._start()

    assert requests == [("wifi-1", str(path))]
    assert dialog.cancel_button.isEnabled() is True
    assert dialog.start_button.isEnabled() is False


def test_dialog_progress_and_state_update_ui(qtbot, tmp_path) -> None:
    dialog = OtaDialog()
    qtbot.addWidget(dialog)
    dialog.set_node("wifi-1")
    dialog.load_package_summary(str(_package(tmp_path, version="1.0.0")))
    dialog._start()

    dialog.on_progress("wifi-1", 512, 1024, "DATA")
    assert dialog.progress_bar.value() == 512
    assert "512" in dialog.status_label.text()

    dialog.on_staged("wifi-1", "1.0.0", "0A1B2C3D", True)
    assert "已暂存" in dialog.status_label.text()

    dialog.on_state("wifi-1", "RECONNECTED", "设备已重连")
    assert dialog.cancel_button.isEnabled() is False
    assert dialog.start_button.isEnabled() is True


def test_dialog_ignores_other_node_signals(qtbot, tmp_path) -> None:
    dialog = OtaDialog()
    qtbot.addWidget(dialog)
    dialog.set_node("wifi-1")

    dialog.on_progress("wifi-2", 10, 100, "DATA")
    dialog.on_state("wifi-2", "FAILED", "boom")

    assert dialog.status_label.text() == "STATUS IDLE"


def test_dialog_close_during_upload_confirms_then_cancels(
    qtbot, tmp_path, monkeypatch
) -> None:
    dialog = OtaDialog()
    qtbot.addWidget(dialog)
    dialog.set_node("wifi-1")
    dialog.load_package_summary(str(_package(tmp_path, version="1.0.0")))
    cancels: list[str] = []
    dialog.cancel_requested.connect(cancels.append)
    dialog._start()
    dialog.show()
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *a, **k: QMessageBox.StandardButton.Yes,
    )

    dialog.close()

    assert cancels == ["wifi-1"]


def test_dialog_close_during_upload_can_be_declined(
    qtbot, tmp_path, monkeypatch
) -> None:
    dialog = OtaDialog()
    qtbot.addWidget(dialog)
    dialog.set_node("wifi-1")
    dialog.load_package_summary(str(_package(tmp_path, version="1.0.0")))
    cancels: list[str] = []
    dialog.cancel_requested.connect(cancels.append)
    dialog._start()
    dialog.show()
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *a, **k: QMessageBox.StandardButton.No,
    )

    dialog.close()

    # Declining keeps the modal dialog open and does not cancel the upload.
    assert cancels == []
    assert dialog.isVisible() is True

    dialog._uploading = False
    dialog.close()
