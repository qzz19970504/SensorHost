"""Main PyQt window implementing the approved dual-focus dashboard shell."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from sensor_host.presentation.vibration_view import VibrationView
from sensor_host.presentation.orientation_view import AttitudeView, OrientationView
from sensor_host.presentation.console_view import ConsoleView
from sensor_host.presentation.diagnostics_view import DiagnosticsView
from sensor_host.acquisition import AcquisitionHealth, UiSnapshot


_DEFAULT_WINDOW_WIDTH = 1440
_DEFAULT_WINDOW_HEIGHT = 900
_CARD_MARGIN = 14
_LAYOUT_SPACING = 10


def _card(title: str) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setProperty("card", True)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(_CARD_MARGIN, _CARD_MARGIN, _CARD_MARGIN, _CARD_MARGIN)
    layout.setSpacing(_LAYOUT_SPACING)
    heading = QLabel(title)
    heading.setProperty("role", "eyebrow")
    layout.addWidget(heading)
    return frame, layout


class MainWindow(QMainWindow):
    """Expose connection controls and dashboard containers to the app controller."""

    connect_requested = pyqtSignal(str)
    disconnect_requested = pyqtSignal()
    pause_toggled = pyqtSignal(bool)
    record_toggled = pyqtSignal(bool)
    watermark_requested = pyqtSignal(int)
    refresh_requested = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("STM32 Sensor Host")
        self.resize(_DEFAULT_WINDOW_WIDTH, _DEFAULT_WINDOW_HEIGHT)
        self.setMinimumSize(1080, 700)

        central_widget = QWidget()
        root_layout = QVBoxLayout(central_widget)
        root_layout.setContentsMargins(18, 12, 18, 16)
        root_layout.setSpacing(_LAYOUT_SPACING)
        self.setCentralWidget(central_widget)

        root_layout.addWidget(self._create_header())
        root_layout.addWidget(self._create_acquisition_toolbar())
        self.tabs = QTabWidget()
        self.live_tab = self._create_live_tab()
        self.diagnostics_view = DiagnosticsView()
        self.diagnostics_tab = self._wrap_tab(self.diagnostics_view)
        self.console_view = ConsoleView()
        self.console_tab = self._wrap_tab(self.console_view)
        self.tabs.addTab(self.live_tab, "LIVE MONITOR")
        self.tabs.addTab(self.diagnostics_tab, "DIAGNOSTICS")
        self.tabs.addTab(self.console_tab, "CONSOLE")
        root_layout.addWidget(self.tabs, stretch=1)

        self.connect_button.clicked.connect(self._emit_connect_requested)
        self.disconnect_button.clicked.connect(self.disconnect_requested)
        self.pause_button.toggled.connect(self.pause_toggled)
        self.record_button.toggled.connect(self.record_toggled)
        self.watermark_combo.currentIndexChanged.connect(
            self._emit_watermark_requested
        )
        self.set_connected(False)

    def set_connected(self, is_connected: bool) -> None:
        """Apply one coherent connected or disconnected control state."""
        self.device_combo.setEnabled(not is_connected)
        self.connect_button.setEnabled(not is_connected)
        self.disconnect_button.setEnabled(is_connected)
        self.pause_button.setEnabled(is_connected)
        self.record_button.setEnabled(is_connected)
        self.watermark_combo.setEnabled(is_connected)
        if is_connected:
            self.connection_badge.setText("● STREAMING")
            self.connection_badge.setProperty("state", "online")
        else:
            self.connection_badge.setText("DISCONNECTED")
            self.connection_badge.setProperty("state", "offline")
            self.pause_button.setChecked(False)
            self.record_button.setChecked(False)
        self.connection_badge.style().unpolish(self.connection_badge)
        self.connection_badge.style().polish(self.connection_badge)

    def set_devices(self, devices: list[tuple[str, str]]) -> None:
        """Replace the selectable CDC device list without opening a port."""
        selected_device = self.device_combo.currentData()
        self.device_combo.clear()
        for device_id, label in devices:
            self.device_combo.addItem(label, device_id)
        if not devices:
            self.device_combo.addItem("No CDC devices", "")
        selected_index = self.device_combo.findData(selected_device)
        if selected_index >= 0:
            self.device_combo.setCurrentIndex(selected_index)

    def update_snapshot(self, snapshot: UiSnapshot) -> None:
        """Refresh all live views and the fixed stream-integrity summary."""
        self.vibration_view.update_snapshot(snapshot)
        self.orientation_view.update_snapshot(snapshot)
        self.attitude_view.update_snapshot(snapshot)
        self.diagnostics_view.update_snapshot(snapshot)
        status = snapshot.firmware_status
        source_drops = 0 if status is None else status.source_drops
        transport_drops = 0 if status is None else status.transport_drops
        cdc_errors = 0 if status is None else status.cdc_errors
        uptime = "—" if status is None else f"{status.uptime_us / 1_000_000.0:.1f}s"
        self.health_summary.setText(
            f"SAMPLES/S {snapshot.sample_rate_hz:,.0f}     "
            f"CRC ERR {snapshot.parser_stats.crc_errors}     "
            f"SEQ GAP {snapshot.parser_stats.sequence_gaps}     "
            f"SOURCE DROP {source_drops}     "
            f"TRANSPORT DROP {transport_drops}     "
            f"CDC ERR {cdc_errors}     UPTIME {uptime}"
        )

    def update_health(self, health: AcquisitionHealth) -> None:
        """Forward host-side counters to the diagnostics page."""
        self.diagnostics_view.update_health(health)

    def _create_header(self) -> QFrame:
        header = QFrame()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        brand = QLabel("STM32 SENSOR DESKTOP")
        brand.setProperty("role", "eyebrow")
        layout.addWidget(brand)
        layout.addStretch(1)
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(250)
        self.device_combo.addItem("No CDC devices", "")
        layout.addWidget(self.device_combo)
        self.connect_button = QPushButton("CONNECT")
        layout.addWidget(self.connect_button)
        self.refresh_button = QPushButton("REFRESH")
        self.refresh_button.clicked.connect(self.refresh_requested)
        layout.addWidget(self.refresh_button)
        self.connection_badge = QLabel("DISCONNECTED")
        self.connection_badge.setMinimumWidth(110)
        layout.addWidget(self.connection_badge)
        self.disconnect_button = QPushButton("DISCONNECT")
        self.disconnect_button.setProperty("role", "danger")
        layout.addWidget(self.disconnect_button)
        return header

    def _create_acquisition_toolbar(self) -> QFrame:
        toolbar = QFrame()
        toolbar.setProperty("card", True)
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(12, 8, 12, 8)
        sensor_label = QLabel("IIS3DWB")
        sensor_label.setProperty("role", "eyebrow")
        layout.addWidget(sensor_label)
        rate_label = QLabel("26.667 kHz")
        rate_label.setProperty("role", "muted")
        layout.addWidget(rate_label)
        layout.addSpacing(18)
        layout.addWidget(QLabel("WINDOW"))
        self.window_combo = QComboBox()
        for seconds in (1, 5, 10, 30):
            self.window_combo.addItem(f"{seconds} s", float(seconds))
        self.window_combo.setCurrentText("10 s")
        layout.addWidget(self.window_combo)
        layout.addWidget(QLabel("FIFO WM"))
        self.watermark_combo = QComboBox()
        for watermark in (128, 256, 511):
            self.watermark_combo.addItem(str(watermark), watermark)
        self.watermark_combo.setCurrentText("256")
        layout.addWidget(self.watermark_combo)
        layout.addStretch(1)
        self.pause_button = QPushButton("Ⅱ PAUSE")
        self.pause_button.setCheckable(True)
        layout.addWidget(self.pause_button)
        self.record_button = QPushButton("● RECORD")
        self.record_button.setCheckable(True)
        layout.addWidget(self.record_button)
        return toolbar

    def _create_live_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(_LAYOUT_SPACING)

        main_splitter = QSplitter()
        vibration_card, self.vibration_container_layout = _card(
            "3-AXIS VIBRATION · g"
        )
        self.vibration_view = VibrationView()
        self.vibration_container_layout.addWidget(self.vibration_view, stretch=1)
        main_splitter.addWidget(vibration_card)

        right_splitter = QSplitter()
        right_splitter.setOrientation(Qt.Orientation.Vertical)
        orientation_card, self.orientation_container_layout = _card(
            "JY61PL ORIENTATION"
        )
        self.orientation_view = OrientationView()
        self.orientation_container_layout.addWidget(self.orientation_view, stretch=1)
        attitude_card, self.attitude_container_layout = _card(
            "ATTITUDE & ACCELERATION"
        )
        self.attitude_view = AttitudeView()
        self.attitude_container_layout.addWidget(self.attitude_view, stretch=1)
        right_splitter.addWidget(orientation_card)
        right_splitter.addWidget(attitude_card)
        right_splitter.setStretchFactor(0, 3)
        right_splitter.setStretchFactor(1, 2)
        main_splitter.addWidget(right_splitter)
        main_splitter.setStretchFactor(0, 2)
        main_splitter.setStretchFactor(1, 1)
        layout.addWidget(main_splitter, stretch=1)

        health_card, self.health_container_layout = _card("STREAM HEALTH")
        health_card.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.health_summary = QLabel(
            "SAMPLES/S —     CRC ERR 0     SEQ GAP 0     SOURCE DROP 0     "
            "TRANSPORT DROP 0     CDC BUSY 0     UPTIME —"
        )
        self.health_summary.setProperty("role", "muted")
        self.health_container_layout.addWidget(self.health_summary)
        layout.addWidget(health_card)
        return tab

    @staticmethod
    def _create_placeholder_tab(title: str) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        card, card_layout = _card(title)
        placeholder = QLabel(f"{title} VIEW")
        placeholder.setProperty("role", "muted")
        card_layout.addWidget(placeholder, stretch=1)
        layout.addWidget(card)
        return tab

    @staticmethod
    def _wrap_tab(view: QWidget) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.addWidget(view)
        return tab

    def _emit_connect_requested(self) -> None:
        device_id = str(self.device_combo.currentData() or "")
        if device_id:
            self.connect_requested.emit(device_id)

    def _emit_watermark_requested(self) -> None:
        watermark = self.watermark_combo.currentData()
        if watermark is not None:
            self.watermark_requested.emit(int(watermark))
