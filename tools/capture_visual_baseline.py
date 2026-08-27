"""Capture a deterministic live-monitor screenshot for manual visual review."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np
from PyQt6.QtWidgets import QApplication

from sensor_host.acquisition import UiSnapshot
from sensor_host.presentation import MainWindow, dark_stylesheet, load_application_fonts
from sensor_host.protocol import Jy61plSample, ParserStats, StatusV1


def _snapshot() -> UiSnapshot:
    time_s = np.linspace(-10.0, 0.0, 2_000, dtype=np.float64)
    orientation = Jy61plSample(
        raw=(0, 0, 2048, 2540, 2257, -674, 23320),
        acceleration_g=(0.03, -0.08, 1.01),
        temperature_c=25.4,
        angles_deg=(12.4, -3.7, 128.1),
    )
    status = StatusV1(
        status_version=1,
        active_transport=0,
        pending_transport=0,
        acquisition_state=1,
        watermark_words=256,
        free_data_buffers=6,
        uart_credit_bytes=0,
        data_queue_peak=2,
        fifo_overruns=0,
        source_drops=0,
        transport_drops=0,
        spi_dma_errors=0,
        uart_dma_errors=0,
        cdc_errors=0,
        command_errors=0,
        iis_stack_high_water_words=512,
        transport_stack_high_water_words=430,
        control_stack_high_water_words=312,
        jy61pl_stack_high_water_words=284,
        led_stack_high_water_words=96,
        uptime_us=132_400_000,
    )
    return UiSnapshot(
        time_s=time_s,
        x_g=0.18 * np.sin(2.0 * np.pi * 18.0 * time_s),
        y_g=0.11 * np.sin(2.0 * np.pi * 27.0 * time_s + 0.7),
        z_g=0.24 * np.sin(2.0 * np.pi * 42.0 * time_s + 1.2),
        orientation=orientation,
        orientation_age_s=0.02,
        firmware_status=status,
        parser_stats=ParserStats(frames=48_372),
        sample_rate_hz=26_666.7,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    application = QApplication.instance() or QApplication(sys.argv)
    load_application_fonts()
    application.setStyleSheet(dark_stylesheet())
    window = MainWindow()
    window.resize(1920, 1080)
    window.set_devices([("COM7", "COM7 — STM32 Virtual COM Port")])
    window.set_connected(True)
    window.update_snapshot(_snapshot())
    window.show()
    application.processEvents()
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    saved = window.grab().save(str(arguments.output), "PNG")
    window.close()
    return 0 if saved else 1


if __name__ == "__main__":
    raise SystemExit(main())
