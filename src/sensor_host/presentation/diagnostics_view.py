"""Fixed-size diagnostics grid for parser, firmware and host counters."""

from __future__ import annotations

from dataclasses import asdict

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QGridLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from sensor_host.acquisition import AcquisitionHealth, UiSnapshot
from sensor_host.presentation.spacing import SPACE


# N-8: STATUS v1 offset 8 (legacy UART credit) is frozen at 0 to preserve the
# binary layout.  Annotate it in the grid so a stuck 0 is not mistaken for a
# live bug.  The StatusV1 dataclass field name and wire semantics are unchanged.
_RESERVED_ALWAYS_ZERO = frozenset({"uart_credit_bytes"})


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
        self.grid.setContentsMargins(
            SPACE.section,
            SPACE.section,
            SPACE.section,
            SPACE.section,
        )
        self.grid.setHorizontalSpacing(SPACE.major)
        self.grid.setVerticalSpacing(SPACE.compact)
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
            "CONTROL STATE",
            (
                "acquisition_state_text",
                "uart_baud",
                "device_uuid",
                "uuid_source",
                "livestream_target",
                "live_drops_iis",
                "live_drops_jy",
                "live_last_routed_sequence",
                "live_last_completed_sequence",
                "sd_used",
                "sd_capacity",
                "sd_pending_frames",
                "sd_retained_chunks",
                "sd_retained_frames",
                "sd_overwritten_chunks",
                "sd_overwritten_frames",
                "sd_ready",
                "sd_format_required",
                "export_target",
                "export_chunk",
                "export_frame",
                "export_phase",
                "export_chunks",
                "export_frames",
                "diag_pool_fail",
                "diag_ingress_drop",
                "diag_nostore_drop",
                "diag_pool_min",
                "diag_ingress_peak",
                "diag_sd_stall_ms",
                "diag_cdc_live",
                "diag_cdc_ctrl",
                "diag_cdc_export",
                "stop_reason",
            ),
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
        if snapshot.firmware_control_state is not None:
            control_values = asdict(snapshot.firmware_control_state)
            control_values["acquisition_state_text"] = control_values.pop(
                "acquisition_state"
            )
            self._replace_values(control_values)

    def update_health(self, health: AcquisitionHealth) -> None:
        self._replace_values(asdict(health))

    def _add_section(self, title: str, fields: tuple[str, ...]) -> None:
        if self._next_row:
            self.grid.setRowMinimumHeight(self._next_row, SPACE.compact)
            self._next_row += 1
        heading = QLabel(title)
        heading.setProperty("role", "eyebrow")
        self.grid.addWidget(heading, self._next_row, 0, 1, 2)
        self._next_row += 1
        for field_name in fields:
            label_text = field_name.replace("_", " ").upper()
            if field_name in _RESERVED_ALWAYS_ZERO:
                label_text += " (RESERVED, ALWAYS 0)"
            label = QLabel(label_text)
            label.setProperty("role", "muted")
            value = QLabel("—")
            value.setWordWrap(True)
            value.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            self.grid.addWidget(label, self._next_row, 0)
            self.grid.addWidget(value, self._next_row, 1)
            self.value_labels[field_name] = value
            self._next_row += 1

    def _replace_values(self, values: dict[str, object]) -> None:
        for key, value in values.items():
            label = self.value_labels.get(key)
            if label is not None:
                text = "—" if value is None else str(value)
                if label.text() != text:
                    label.setText(text)
