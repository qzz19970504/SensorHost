from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import numpy as np
from PyQt6.QtWidgets import QApplication, QLabel

from sensor_host.acquisition import (
    AcquisitionHealth,
    ConnectionState,
    NodeSummary,
    TransportKind,
    empty_snapshot,
)
from sensor_host.presentation.app_controller import SdRecordInfo
from sensor_host.presentation.connection_view import NetworkInterfaceInfo
from sensor_host.presentation.main_window import MainWindow
from sensor_host.presentation.theme import dark_stylesheet, load_application_fonts
from sensor_host.protocol import FirmwareControlState, Jy61plSample, ParserStats, StatusV1


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "docs" / "artifacts"
CAPTURE_DATA = ROOT / "build" / "guide_capture_data"
DEVICE_UUID = UUID("49005000-0e50-8731-9432-39203731a4f8")
NODE_ID = "guide-node-1"
LOCAL_IPV4 = "192.168.137.201"
PEER_IPV4 = "192.168.137.202"


def prepare_local_export() -> Path:
    export_dir = CAPTURE_DATA / "exports" / "20260911T083200Z" / "Node-49005000"
    export_dir.mkdir(parents=True, exist_ok=True)
    archive = export_dir / "export-001.sdf1"
    archive.write_bytes(b"SDF1 guide screenshot fixture")
    metadata = {
        "format": "SDF1_ARCHIVE_EXPORT",
        "started_utc": "2026-09-11T08:32:00+00:00",
        "ended_utc": "2026-09-11T08:33:18+00:00",
        "bytes_written": 1843200,
        "status": "complete",
        "alias": "Field Node A",
        "uuid": str(DEVICE_UUID),
    }
    archive.with_suffix(".json").write_text(
        json.dumps(metadata, ensure_ascii=False), encoding="utf-8"
    )
    return archive


def build_node() -> NodeSummary:
    return NodeSummary(
        node_id=NODE_ID,
        transport_kind=TransportKind.WIFI,
        peer=PEER_IPV4,
        connection_state=ConnectionState.STREAMING,
        device_uuid=DEVICE_UUID,
        alias="Field Node A",
    )


def build_record(phase: str | None = None) -> SdRecordInfo:
    return SdRecordInfo(
        node_id=NODE_ID,
        alias="Field Node A",
        uuid_suffix="3731a4f8",
        transport="wifi",
        sd_ready=True,
        sd_format_required=False,
        used_bytes=124776448,
        capacity_bytes=124776448,
        retained_frames=33329,
        retained_chunks=30463,
        overwritten_frames=2812119,
        estimated_duration_s=125.0,
        export_phase=phase,
    )


def build_snapshot():
    time_s = np.linspace(-10.0, 0.0, 2000)
    empty = empty_snapshot()
    return replace(
        empty,
        time_s=time_s,
        x_g=0.08 * np.sin(time_s * 20.0),
        y_g=0.12 * np.sin(time_s * 16.0 + 1.0),
        z_g=1.0 + 0.05 * np.sin(time_s * 12.0),
        orientation=Jy61plSample(
            raw=(0, 0, 0, 0, 0, 0, 0),
            acceleration_g=(0.02, -0.01, 1.00),
            temperature_c=26.4,
            angles_deg=(1.2, -0.6, 42.5),
        ),
        orientation_age_s=0.08,
        firmware_status=StatusV1(
            status_version=1,
            active_transport=1,
            pending_transport=1,
            acquisition_state=1,
            watermark_words=256,
            free_data_buffers=5,
            uart_credit_bytes=0,
            data_queue_peak=12,
            fifo_overruns=0,
            source_drops=0,
            transport_drops=0,
            spi_dma_errors=0,
            uart_dma_errors=0,
            cdc_errors=0,
            command_errors=0,
            iis_stack_high_water_words=120,
            transport_stack_high_water_words=96,
            control_stack_high_water_words=80,
            jy61pl_stack_high_water_words=88,
            led_stack_high_water_words=40,
            uptime_us=184_200_000,
        ),
        parser_stats=ParserStats(
            frames=123456,
            crc_errors=0,
            sequence_gaps=0,
        ),
        sample_rate_hz=26_667.0,
        firmware_control_state=FirmwareControlState(
            acquisition_state="ACQUIRE",
            uart_baud=921600,
            device_uuid=DEVICE_UUID,
            uuid_source="FLASH",
            sd_used=124_776_448,
            sd_capacity=124_776_448,
            sd_pending_frames=0,
            sd_retained_chunks=30463,
            sd_retained_frames=33329,
            sd_overwritten_chunks=2812,
            sd_overwritten_frames=2812119,
            sd_ready=True,
            sd_format_required=False,
            livestream_target="UART",
            live_drops_iis=0,
            live_drops_jy=0,
            live_last_routed_sequence=123455,
            live_last_completed_sequence=123454,
        ),
    )


def sanitize_wifi_labels(window: MainWindow) -> None:
    """Use neutral labels in guide screenshots without changing the product UI."""
    replacements = {
        "PC IPv4 PRESET IN ESP FIRMWARE": "PC IPv4 PRESET IN DEVICE CONFIG",
        "OPTIONAL ESP IPv4 TARGETS": "OPTIONAL DEVICE IPv4 TARGETS",
        "PC and every ESP must join the same phone hotspot. The selected PC IPv4 must match the address compiled into each ESP. If no gateway connects, check hotspot client isolation and allow inbound TCP in Windows Firewall.": (
            "PC and every device must join the same phone hotspot. The selected PC IPv4 must match the address configured on the device side. If no gateway connects, check hotspot client isolation and allow inbound TCP in Windows Firewall."
        ),
    }
    for label in window.wifi_panel.findChildren(QLabel):
        if label.text() in replacements:
            label.setText(replacements[label.text()])


def setup_window(app: QApplication) -> MainWindow:
    window = MainWindow()
    window.resize(1440, 900)
    window.set_network_interfaces(
        [NetworkInterfaceInfo("Mobile Hotspot", LOCAL_IPV4, "255.255.255.0")]
    )
    window.transport_mode_combo.setCurrentText("WI-FI")
    window.wifi_panel.expected_ipv4_edit.setText(LOCAL_IPV4)
    window.wifi_panel.tcp_port_spin.setValue(54321)
    window.wifi_panel.udp_port_spin.setValue(12345)
    window.wifi_panel.wake_targets_edit.setText(PEER_IPV4)
    window.live_target_combo.setCurrentText("UART")
    window.workspace_splitter.setSizes([315, 1125])
    sanitize_wifi_labels(window)
    return window


def capture_wifi_screens(window: MainWindow) -> None:
    window.set_nodes([])
    window.set_wifi_server_state(False, "DISCONNECTED")
    window.tabs.setCurrentWidget(window.live_tab)
    window.left_splitter.setSizes([520, 170])
    window.show()
    QApplication.processEvents()
    window.grab().save(str(OUTPUT_DIR / "sensorhost_wifi_connection.png"))

    window.set_nodes([build_node()])
    window.set_wifi_server_state(True, f"LISTENING {LOCAL_IPV4}:54321")
    window.left_splitter.setSizes([385, 305])
    window.live_target_combo.setCurrentText("UART")
    window.update_snapshot(build_snapshot())
    QApplication.processEvents()
    window.grab().save(str(OUTPUT_DIR / "sensorhost_wifi_live.png"))

    window.tabs.setCurrentWidget(window.diagnostics_tab)
    window.update_snapshot(build_snapshot())
    window.update_health(
        AcquisitionHealth(bytes_received=8_640_000, frames_received=123456)
    )
    QApplication.processEvents()
    window.grab().save(str(OUTPUT_DIR / "sensorhost_wifi_diagnostics.png"))

    window.tabs.setCurrentWidget(window.console_tab)
    window.console_view.transcript.clear()
    window.console_view.set_current_node(NODE_ID)
    window.console_view.append_local(
        f"Wi-Fi listener active at {LOCAL_IPV4}:54321; UDP wake 12345"
    )
    window.console_view.append_response("+UUID:49005000-0e50-8731-9432-39203731A4F8")
    window.console_view.append_response("+STATE:ACQUIRE")
    window.console_view.append_response("+LIVESTREAM:UART")
    window.console_view.append_response("OK")
    QApplication.processEvents()
    window.grab().save(str(OUTPUT_DIR / "sensorhost_wifi_console.png"))


def capture_archive_screens(window: MainWindow) -> None:
    archive = window.archive_view
    window.set_nodes([build_node()])
    window.set_wifi_server_state(True, f"LISTENING {LOCAL_IPV4}:54321")
    archive.set_records([build_record()])
    archive.record_table.selectRow(0)
    archive.refresh_library()
    archive.library_table.selectRow(0)
    window.tabs.setCurrentWidget(window.archive_tab)
    archive.archive_splitter.setSizes([365, 205, 300])
    window.show()
    QApplication.processEvents()
    (OUTPUT_DIR / "sensorhost_sd_archive_overview.png").parent.mkdir(
        parents=True, exist_ok=True
    )
    window.grab().save(str(OUTPUT_DIR / "sensorhost_sd_archive_overview.png"))

    archive._export_node_id = NODE_ID
    archive._export_started_ms = archive._now_ms() - 12500
    archive._last_bytes = 0
    archive._last_bytes_ms = 0
    archive._update_progress(
        NODE_ID,
        True,
        1572864,
        124776448,
        "IN PROGRESS",
    )
    archive.cancel_button.setEnabled(True)
    QApplication.processEvents()
    window.grab().save(str(OUTPUT_DIR / "sensorhost_sd_export_progress.png"))


def capture_playback_screen(window: MainWindow) -> None:
    snapshot = build_snapshot()
    window.set_playback_active(True)
    window.playback_bar.set_file_name("export-001.sdf1")
    window.playback_bar.set_state(False, 12.0, 30.0)
    window.update_snapshot(snapshot)
    QApplication.processEvents()
    window.grab().save(str(OUTPUT_DIR / "sensorhost_playback_controls.png"))


def main() -> None:
    CAPTURE_DATA.mkdir(parents=True, exist_ok=True)
    os.environ["SENSOR_HOST_DATA_DIR"] = str(CAPTURE_DATA)
    prepare_local_export()
    app = QApplication.instance() or QApplication([])
    load_application_fonts()
    app.setStyleSheet(dark_stylesheet())
    window = setup_window(app)
    capture_wifi_screens(window)
    capture_archive_screens(window)
    capture_playback_screen(window)
    window.close()
    print(OUTPUT_DIR)


if __name__ == "__main__":
    main()
