from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import numpy as np
from PyQt6.QtWidgets import QApplication

from sensor_host.acquisition import ConnectionState, NodeSummary, TransportKind, empty_snapshot
from sensor_host.presentation.app_controller import SdRecordInfo
from sensor_host.presentation.main_window import MainWindow
from sensor_host.presentation.theme import dark_stylesheet, load_application_fonts


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "docs" / "artifacts"
CAPTURE_DATA = ROOT / "build" / "guide_capture_data"
DEVICE_UUID = UUID("49005000-0e50-8731-9432-39203731a4f8")
NODE_ID = "guide-node-1"


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
        "alias": "Node 49005000",
        "uuid": str(DEVICE_UUID),
    }
    archive.with_suffix(".json").write_text(
        json.dumps(metadata, ensure_ascii=False), encoding="utf-8"
    )
    return archive


def build_node() -> NodeSummary:
    return NodeSummary(
        node_id=NODE_ID,
        transport_kind=TransportKind.CDC,
        peer="COM6",
        connection_state=ConnectionState.CONNECTED,
        device_uuid=DEVICE_UUID,
        alias="Node 49005000",
    )


def build_record(phase: str | None = None) -> SdRecordInfo:
    return SdRecordInfo(
        node_id=NODE_ID,
        alias="Node 49005000",
        uuid_suffix="3731a4f8",
        transport="cdc",
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


def setup_window(app: QApplication) -> MainWindow:
    window = MainWindow()
    window.resize(1440, 900)
    window.set_devices([("COM6", "COM6 — STM32 Virtual COM Port")])
    window.transport_mode_combo.setCurrentText("CDC")
    window.live_target_combo.setCurrentText("CDC")
    window.set_nodes([build_node()])
    window.set_connected(True)
    window.workspace_splitter.setSizes([260, 1180])
    return window


def capture_archive_screens(window: MainWindow) -> None:
    archive = window.archive_view
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
    time_s = np.linspace(-10.0, 0.0, 2000)
    snapshot = replace(
        empty_snapshot(),
        time_s=time_s,
        x_g=0.08 * np.sin(time_s * 20.0),
        y_g=0.12 * np.sin(time_s * 16.0 + 1.0),
        z_g=1.0 + 0.05 * np.sin(time_s * 12.0),
        sample_rate_hz=20000.0,
    )
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
    capture_archive_screens(window)
    capture_playback_screen(window)
    window.close()
    print(OUTPUT_DIR)


if __name__ == "__main__":
    main()
