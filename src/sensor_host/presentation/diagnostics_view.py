"""Fixed-size diagnostics grid for parser, firmware and host counters."""

from __future__ import annotations

from dataclasses import asdict

from PyQt6.QtWidgets import QGridLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from sensor_host.acquisition import AcquisitionHealth, UiSnapshot


class DiagnosticsView(QWidget):
    """Replace counter labels in place without allocating per-frame widgets."""

    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        contents = QWidget()
        self.grid = QGridLayout(contents)
        self.grid.setColumnStretch(1, 1)
        scroll.setWidget(contents)
        root.addWidget(scroll)
        self.value_labels: dict[str, QLabel] = {}
        self._next_row = 0
        self._add_section(
            "PARSER",
            (
                "frames",
                "bytes_discarded",
                "crc_errors",
                "header_errors",
                "unknown_versions",
                "length_errors",
                "unknown_types",
                "payload_errors",
                "sequence_gaps",
            ),
        )
        self._add_section(
            "HOST",
            ("bytes_received", "frames_received", "recording_failure", "last_error"),
        )
        self._add_section(
            "FIRMWARE",
            (
                "status_version",
                "active_transport",
                "pending_transport",
                "acquisition_state",
                "watermark_words",
                "free_data_buffers",
                "uart_credit_bytes",
                "data_queue_peak",
                "fifo_overruns",
                "source_drops",
                "transport_drops",
                "spi_dma_errors",
                "uart_dma_errors",
                "cdc_errors",
                "command_errors",
                "iis_stack_high_water_words",
                "transport_stack_high_water_words",
                "control_stack_high_water_words",
                "jy61pl_stack_high_water_words",
                "led_stack_high_water_words",
                "uptime_us",
            ),
        )

    def update_snapshot(self, snapshot: UiSnapshot) -> None:
        self._replace_values(asdict(snapshot.parser_stats))
        if snapshot.firmware_status is not None:
            self._replace_values(asdict(snapshot.firmware_status))

    def update_health(self, health: AcquisitionHealth) -> None:
        self._replace_values(asdict(health))

    def _add_section(self, title: str, fields: tuple[str, ...]) -> None:
        heading = QLabel(title)
        heading.setProperty("role", "eyebrow")
        self.grid.addWidget(heading, self._next_row, 0, 1, 2)
        self._next_row += 1
        for field_name in fields:
            label = QLabel(field_name.replace("_", " ").upper())
            label.setProperty("role", "muted")
            value = QLabel("—")
            self.grid.addWidget(label, self._next_row, 0)
            self.grid.addWidget(value, self._next_row, 1)
            self.value_labels[field_name] = value
            self._next_row += 1

    def _replace_values(self, values: dict[str, object]) -> None:
        for key, value in values.items():
            label = self.value_labels.get(key)
            if label is not None:
                label.setText("—" if value is None else str(value))

