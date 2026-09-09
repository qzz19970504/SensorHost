"""Main PyQt window implementing the approved dual-focus dashboard shell."""

from __future__ import annotations

from PyQt6.QtCore import QSettings, QSignalBlocker, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QIcon, QShowEvent
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from sensor_host.branding import (
    APPLICATION_BRAND,
    APPLICATION_ICON_PATH,
    APPLICATION_NAME,
    ORIENTATION_SENSOR_LABEL,
    VIBRATION_SENSOR_LABEL,
)
from sensor_host.presentation.native_chrome import apply_windows_title_bar
from sensor_host.presentation.vibration_view import VibrationView
from sensor_host.presentation.controls import IntegratedComboBox
from sensor_host.presentation.orientation_view import AttitudeView, OrientationView
from sensor_host.presentation.console_view import ConsoleView
from sensor_host.presentation.diagnostics_view import DiagnosticsView
from sensor_host.presentation.spacing import SPACE
from sensor_host.presentation.connection_view import (
    NetworkInterfaceInfo,
    NodeSidebar,
    WifiConnectionPanel,
)
from sensor_host.acquisition import AcquisitionHealth, ConnectionState, NodeSummary, UiSnapshot
from sensor_host.presentation.splitter import CapsuleSplitter


_DEFAULT_WINDOW_WIDTH = 1440
_DEFAULT_WINDOW_HEIGHT = 900
_WORKSPACE_SPLIT_SIZES = (260, 1180)
_MAIN_SPLIT_SIZES = (1000, 420)
_RIGHT_SPLIT_SIZES = (500, 400)
_CARD_TITLE_ACCENT_WIDTH = 3
_CARD_TITLE_ACCENT_HEIGHT = 20
_COMBO_MINIMUM_WIDTH = 72
_TAB_BAR_HEIGHT = 38
_LIVESTREAM_SYNC_GRACE_MS = 500
_ERROR_HEALTH_KEYS = (
    "crc_errors",
    "sequence_gaps",
    "source_drops",
    "transport_drops",
    "physical_errors",
    "live_drops",
)


def _card_header(title: str, actions: QWidget | None = None) -> QFrame:
    header = QFrame()
    header.setProperty("role", "card-header")
    layout = QHBoxLayout(header)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(SPACE.compact)

    accent = QFrame()
    accent.setProperty("role", "title-accent")
    accent.setFixedSize(_CARD_TITLE_ACCENT_WIDTH, _CARD_TITLE_ACCENT_HEIGHT)
    layout.addWidget(accent)

    heading = QLabel(title)
    heading.setProperty("role", "card-title")
    layout.addWidget(heading)
    layout.addStretch(1)
    if actions is not None:
        layout.addWidget(actions, alignment=Qt.AlignmentFlag.AlignVCenter)

    return header


def _card(
    title: str,
    actions: QWidget | None = None,
) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setProperty("card", True)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(
        SPACE.section,
        SPACE.section,
        SPACE.section,
        SPACE.section,
    )
    layout.setSpacing(SPACE.section)
    header = _card_header(title, actions)
    layout.addWidget(header)
    return frame, layout


def _toolbar_divider() -> QFrame:
    divider = QFrame()
    divider.setProperty("role", "toolbar-divider")
    divider.setFixedSize(1, 22)
    return divider


class MainWindow(QMainWindow):
    """Expose connection controls and dashboard containers to the app controller."""

    connect_requested = pyqtSignal(str)
    disconnect_requested = pyqtSignal()
    clear_requested = pyqtSignal()
    pause_toggled = pyqtSignal(bool)
    record_toggled = pyqtSignal(bool)
    watermark_requested = pyqtSignal(int)
    start_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    livestream_requested = pyqtSignal(str)
    refresh_requested = pyqtSignal()
    wifi_start_requested = pyqtSignal(object)

    def __init__(self, settings: QSettings | None = None) -> None:
        super().__init__()
        self._settings = settings
        self.setWindowTitle(APPLICATION_NAME)
        self.setWindowIcon(QIcon(str(APPLICATION_ICON_PATH)))
        self.resize(_DEFAULT_WINDOW_WIDTH, _DEFAULT_WINDOW_HEIGHT)
        self.setMinimumSize(960, 540)
        self._pending_livestream_target: str | None = None
        self._connected = False
        self._node_available = False
        self._latest_snapshot: UiSnapshot | None = None

        central_widget = QWidget()
        root_layout = QVBoxLayout(central_widget)
        root_layout.setContentsMargins(
            SPACE.major,
            SPACE.section,
            SPACE.major,
            SPACE.major,
        )
        root_layout.setSpacing(SPACE.normal)
        self.setCentralWidget(central_widget)

        self.app_header = self._create_header()
        root_layout.addWidget(self.app_header)
        root_layout.addWidget(self._create_acquisition_toolbar())
        root_layout.addWidget(self._create_error_banner())
        self.tabs = QTabWidget()
        self.tabs.tabBar().setFixedHeight(_TAB_BAR_HEIGHT)
        self.live_tab = self._create_live_tab()
        self.diagnostics_view = DiagnosticsView()
        self.diagnostics_tab = self._wrap_tab(self.diagnostics_view)
        self.console_view = ConsoleView()
        self.console_tab = self._wrap_tab(self.console_view)
        self.tabs.addTab(self.live_tab, "LIVE MONITOR")
        self.tabs.addTab(self.diagnostics_tab, "DIAGNOSTICS")
        self.tabs.addTab(self.console_tab, "CONSOLE")
        self.wifi_panel = WifiConnectionPanel()
        self.node_sidebar = NodeSidebar()
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(SPACE.normal)
        left_layout.addWidget(self.wifi_panel)
        left_layout.addWidget(self.node_sidebar, stretch=1)
        self.workspace_splitter = CapsuleSplitter()
        self.workspace_splitter.addWidget(left_panel)
        self.workspace_splitter.addWidget(self.tabs)
        self.workspace_splitter.setStretchFactor(0, 1)
        self.workspace_splitter.setStretchFactor(1, 5)
        self.workspace_splitter.setSizes(list(_WORKSPACE_SPLIT_SIZES))
        root_layout.addWidget(self.workspace_splitter, stretch=1)

        self.connect_button.clicked.connect(self._emit_connect_requested)
        self.vibration_view.clear_button.clicked.connect(self._clear_canvas)
        self.pause_button.toggled.connect(self.pause_toggled)
        self.record_button.toggled.connect(self.record_toggled)
        self.start_button.clicked.connect(self.start_requested)
        self.stop_button.clicked.connect(self.stop_requested)
        self.live_target_combo.currentTextChanged.connect(
            self._emit_livestream_requested
        )
        self.watermark_combo.currentIndexChanged.connect(
            self._emit_watermark_requested
        )
        self.transport_mode_combo.currentTextChanged.connect(
            self._update_transport_mode
        )
        self.console_view.message_appended.connect(self._on_console_message)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self._update_transport_mode()
        self.set_connected(False)
        self._define_tab_order()
        self._restore_layout()

    def set_connected(self, is_connected: bool) -> None:
        """Apply one coherent connected or disconnected control state."""
        if not is_connected:
            self._pending_livestream_target = None
        self.device_combo.setEnabled(not is_connected)
        self.transport_mode_combo.setEnabled(not is_connected)
        self.wifi_panel.setEnabled(not is_connected)
        self.connect_button.setText("DISCONNECT" if is_connected else "CONNECT")
        self.connect_button.setAccessibleName("Disconnect" if is_connected else "Connect")
        self.connect_button.setProperty("role", "danger" if is_connected else "primary")
        self.connect_button.style().unpolish(self.connect_button)
        self.connect_button.style().polish(self.connect_button)
        self._connected = is_connected
        if is_connected:
            self.connection_badge.setText("● CONNECTED")
            self.connection_badge.setProperty("state", "online")
        else:
            self.connection_badge.setText("DISCONNECTED")
            self.connection_badge.setProperty("state", "offline")
            self.pause_button.setChecked(False)
            self.record_button.setChecked(False)
            self.orientation_view.set_offline()
        self.connection_badge.style().unpolish(self.connection_badge)
        self.connection_badge.style().polish(self.connection_badge)
        self._refresh_node_controls()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        apply_windows_title_bar(self)

    def _clear_canvas(self) -> None:
        """Discard cached plot history even while the display is frozen."""
        self._latest_snapshot = None
        self.vibration_view.clear()
        self.clear_requested.emit()

    def set_display_paused(self, is_paused: bool) -> None:
        """Mark every display-frozen view so frozen values are not read as live."""
        self.vibration_view.set_paused(is_paused)
        self.orientation_view.set_paused(is_paused)

    def _refresh_node_controls(self) -> None:
        """Enable node-scoped actions only when a connected node can receive them."""
        node_ready = self._connected and self._node_available
        reason = "" if node_ready else "connect a node before using node commands"
        for widget in (
            self.pause_button,
            self.record_button,
            self.watermark_combo,
            self.live_target_combo,
            self.start_button,
            self.stop_button,
        ):
            widget.setEnabled(node_ready)
            widget.setToolTip(reason)

    def show_error(self, message: str) -> None:
        """Surface one non-modal error outside the console tab."""
        self.error_banner.setText(f"ERROR: {message}")
        self.error_banner_frame.setVisible(True)

    def _on_console_message(self, _message: str) -> None:
        if self.tabs.currentWidget() is not self.console_tab:
            self.tabs.setTabText(self.tabs.indexOf(self.console_tab), "CONSOLE ●")

    def _on_tab_changed(self, _index: int) -> None:
        if self.tabs.currentWidget() is self.console_tab:
            self.tabs.setTabText(self.tabs.indexOf(self.console_tab), "CONSOLE")
        if self._latest_snapshot is not None:
            self.update_snapshot(self._latest_snapshot)

    def _reset_layout(self) -> None:
        """Restore default splitter proportions and window size (UI-24)."""
        if self._settings is not None:
            self._settings.beginGroup("ui")
            self._settings.remove("")
            self._settings.endGroup()
        self.workspace_splitter.setSizes(list(_WORKSPACE_SPLIT_SIZES))
        self.main_splitter.setSizes(list(_MAIN_SPLIT_SIZES))
        self.right_splitter.setSizes(list(_RIGHT_SPLIT_SIZES))
        self.resize(_DEFAULT_WINDOW_WIDTH, _DEFAULT_WINDOW_HEIGHT)

    def _define_tab_order(self) -> None:
        """Pin a stable keyboard tab order across the primary controls (UI-18)."""
        chain = (
            self.transport_mode_combo,
            self.device_combo,
            self.connect_button,
            self.refresh_button,
            self.reset_layout_button,
            self.window_combo,
            self.watermark_combo,
            self.live_target_combo,
            self.start_button,
            self.stop_button,
            self.pause_button,
            self.record_button,
        )
        for previous, current in zip(chain, chain[1:]):
            self.setTabOrder(previous, current)

    def save_layout(self) -> None:
        """Persist window geometry and splitter sizes under ui/* keys (UI-24)."""
        if self._settings is None:
            return
        self._settings.beginGroup("ui")
        try:
            self._settings.setValue("window_width", self.width())
            self._settings.setValue("window_height", self.height())
            self._settings.setValue(
                "workspace_sizes", self.workspace_splitter.sizes()
            )
            self._settings.setValue("main_sizes", self.main_splitter.sizes())
            self._settings.setValue("right_sizes", self.right_splitter.sizes())
        finally:
            self._settings.endGroup()

    def _restore_layout(self) -> None:
        """Apply persisted ui/* layout if valid, clamped to the work area."""
        if self._settings is None:
            return
        self._settings.beginGroup("ui")
        try:
            width = self._settings.value("window_width", 0, type=int)
            height = self._settings.value("window_height", 0, type=int)
            workspace = self._settings.value("workspace_sizes", [], type=list)
            main = self._settings.value("main_sizes", [], type=list)
            right = self._settings.value("right_sizes", [], type=list)
        finally:
            self._settings.endGroup()
        screen = self.screen()
        if width > 0 and height > 0:
            if screen is not None:
                available = screen.availableGeometry()
                width = min(width, available.width())
                height = min(height, available.height())
            self.resize(
                max(width, self.minimumWidth()), max(height, self.minimumHeight())
            )
        for splitter, sizes in (
            (self.workspace_splitter, workspace),
            (self.main_splitter, main),
            (self.right_splitter, right),
        ):
            try:
                parsed = [int(value) for value in sizes]
            except (TypeError, ValueError):
                parsed = []
            if len(parsed) == 2 and all(value > 0 for value in parsed):
                splitter.setSizes(parsed)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API name
        self.save_layout()
        super().closeEvent(event)

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

    def set_network_interfaces(self, interfaces: list[NetworkInterfaceInfo]) -> None:
        """Replace the active hotspot-capable IPv4 interface list."""
        self.wifi_panel.set_network_interfaces(interfaces)

    def set_nodes(self, nodes: list[NodeSummary]) -> None:
        """Replace the persistent multi-node sidebar content."""
        self.node_sidebar.set_nodes(nodes)
        self._node_available = any(
            node.connection_state
            in {ConnectionState.CONNECTED, ConnectionState.STREAMING}
            for node in nodes
        )
        recording_count = sum(1 for node in nodes if node.is_recording)
        self.record_button.setText(
            f"● RECORD · {recording_count}" if recording_count else "● RECORD"
        )
        self.record_button.setToolTip(
            f"recording {recording_count} of {len(nodes)} session(s); "
            "write failures surface in the error banner"
        )
        self._refresh_node_controls()

    def set_wifi_server_state(self, is_running: bool, label: str) -> None:
        """Show listener state even before the first gateway connects."""
        self.set_connected(is_running)
        if is_running:
            self.connection_badge.setText(label)

    def update_snapshot(self, snapshot: UiSnapshot) -> None:
        """Refresh only the visible page, caching the snapshot for tab returns."""
        self._latest_snapshot = snapshot
        control_state = snapshot.firmware_control_state
        reported_livestream_target = (
            None if control_state is None else control_state.livestream_target
        )
        if reported_livestream_target == self._pending_livestream_target:
            self._pending_livestream_target = None
        if (
            self._pending_livestream_target is None
            and reported_livestream_target in {"UART", "CDC"}
            and self.live_target_combo.currentText()
            != reported_livestream_target
        ):
            signal_blocker = QSignalBlocker(self.live_target_combo)
            self.live_target_combo.setCurrentText(reported_livestream_target)
            del signal_blocker
        current = self.tabs.currentWidget()
        if current is self.diagnostics_tab:
            self.diagnostics_view.update_snapshot(snapshot)
            return
        if current is not self.live_tab:
            return
        self.vibration_view.update_snapshot(snapshot)
        self.orientation_view.update_snapshot(snapshot)
        self.attitude_view.update_snapshot(snapshot)
        self._update_health_labels(snapshot)

    def _update_health_labels(self, snapshot: UiSnapshot) -> None:
        status = snapshot.firmware_status
        unknown = "—"
        source_drops = unknown if status is None else str(status.source_drops)
        transport_drops = unknown if status is None else str(status.transport_drops)
        is_wifi = self.transport_mode_combo.currentText() == "WI-FI"
        if status is None:
            physical_errors = unknown
        else:
            physical_errors = str(
                status.uart_dma_errors if is_wifi else status.cdc_errors
            )
        control_state = snapshot.firmware_control_state
        if control_state is None:
            live_drops = unknown
        else:
            live_drops = str(
                (control_state.live_drops_iis or 0) + (control_state.live_drops_jy or 0)
            )
        uptime = unknown if status is None else f"{status.uptime_us / 1_000_000.0:.1f}s"
        health_values = {
            "sample_rate": f"{snapshot.sample_rate_hz:,.0f}",
            "crc_errors": str(snapshot.parser_stats.crc_errors),
            "sequence_gaps": str(snapshot.parser_stats.sequence_gaps),
            "source_drops": source_drops,
            "transport_drops": transport_drops,
            "physical_errors": physical_errors,
            "live_drops": live_drops,
            "uptime": uptime,
        }
        for key, value in health_values.items():
            label = self.health_value_labels[key]
            if label.text() != value:
                label.setText(value)
            if key in _ERROR_HEALTH_KEYS and value not in ("0", unknown):
                label.setToolTip(f"{key} is non-zero; open DIAGNOSTICS for detail")
            else:
                label.setToolTip("")

    def update_health(self, health: AcquisitionHealth) -> None:
        """Forward host-side counters to the diagnostics page."""
        self.diagnostics_view.update_health(health)

    def _create_header(self) -> QFrame:
        header = QFrame()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, SPACE.tight, 0, SPACE.tight)
        layout.setSpacing(SPACE.compact)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        brand = QLabel(APPLICATION_BRAND)
        brand.setProperty("role", "eyebrow")
        layout.addWidget(brand)
        layout.addStretch(1)
        self.transport_mode_combo = IntegratedComboBox()
        self.transport_mode_combo.addItems(("CDC", "WI-FI"))
        self.transport_mode_combo.setAccessibleName("Transport mode")
        layout.addWidget(self.transport_mode_combo)
        self.device_combo = IntegratedComboBox()
        self.device_combo.setMinimumWidth(250)
        self.device_combo.addItem("No CDC devices", "")
        self.device_combo.setAccessibleName("CDC device")
        layout.addWidget(self.device_combo)
        self.connect_button = QPushButton("CONNECT")
        self.connect_button.setProperty("role", "primary")
        self.connect_button.setAccessibleName("Connect")
        layout.addWidget(self.connect_button)
        self.refresh_button = QPushButton("REFRESH")
        self.refresh_button.clicked.connect(self.refresh_requested)
        self.refresh_button.setAccessibleName("Refresh devices")
        layout.addWidget(self.refresh_button)
        self.connection_badge = QLabel("DISCONNECTED")
        self.connection_badge.setMinimumWidth(110)
        layout.addWidget(self.connection_badge)
        self.reset_layout_button = QPushButton("RESET LAYOUT")
        self.reset_layout_button.clicked.connect(self._reset_layout)
        self.reset_layout_button.setAccessibleName("Reset layout")
        layout.addWidget(self.reset_layout_button)
        return header

    def _create_acquisition_toolbar(self) -> QFrame:
        toolbar = QFrame()
        self.acquisition_toolbar = toolbar
        toolbar.setProperty("card", True)
        toolbar.setMinimumHeight(50)
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(
            SPACE.section,
            SPACE.compact,
            SPACE.section,
            SPACE.compact,
        )
        layout.setSpacing(SPACE.compact)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        sensor_label = QLabel(VIBRATION_SENSOR_LABEL)
        sensor_label.setProperty("role", "eyebrow")
        rate_label = QLabel("26.667 kHz")
        rate_label.setProperty("role", "muted")
        layout.addWidget(sensor_label)
        layout.addWidget(rate_label)
        layout.addWidget(_toolbar_divider())

        window_label = QLabel("WINDOW")
        window_label.setProperty("role", "control-label")
        self.window_combo = IntegratedComboBox()
        self.window_combo.setMinimumWidth(_COMBO_MINIMUM_WIDTH)
        for seconds in (1, 5, 10, 30):
            self.window_combo.addItem(f"{seconds} s", float(seconds))
        self.window_combo.setCurrentText("10 s")
        self.window_combo.setAccessibleName("Display window seconds")
        window_label.setBuddy(self.window_combo)
        layout.addWidget(window_label)
        layout.addWidget(self.window_combo)
        layout.addWidget(_toolbar_divider())

        watermark_label = QLabel("FIFO WM")
        watermark_label.setProperty("role", "control-label")
        self.watermark_combo = IntegratedComboBox()
        self.watermark_combo.setMinimumWidth(_COMBO_MINIMUM_WIDTH)
        for watermark in (128, 256, 511):
            self.watermark_combo.addItem(str(watermark), watermark)
        self.watermark_combo.setCurrentText("256")
        self.watermark_combo.setAccessibleName("FIFO watermark")
        watermark_label.setBuddy(self.watermark_combo)
        layout.addWidget(watermark_label)
        layout.addWidget(self.watermark_combo)
        layout.addWidget(_toolbar_divider())

        live_target_label = QLabel("LIVE TARGET")
        live_target_label.setProperty("role", "control-label")
        self.live_target_combo = IntegratedComboBox()
        self.live_target_combo.setMinimumWidth(_COMBO_MINIMUM_WIDTH)
        self.live_target_combo.addItems(("UART", "CDC"))
        self.live_target_combo.setAccessibleName("Live target")
        live_target_label.setBuddy(self.live_target_combo)
        layout.addWidget(live_target_label)
        layout.addWidget(self.live_target_combo)
        self.start_button = QPushButton("START")
        self.start_button.setProperty("role", "primary")
        self.start_button.setAccessibleName("Start acquisition")
        layout.addWidget(self.start_button)
        self.stop_button = QPushButton("STOP")
        self.stop_button.setProperty("role", "danger")
        self.stop_button.setAccessibleName("Stop acquisition")
        layout.addWidget(self.stop_button)
        layout.addStretch(1)
        self.pause_button = QPushButton("Ⅱ PAUSE")
        self.pause_button.setCheckable(True)
        self.pause_button.setAccessibleName("Pause display")
        layout.addWidget(self.pause_button)
        self.record_button = QPushButton("● RECORD")
        self.record_button.setCheckable(True)
        self.record_button.setAccessibleName("Record all sessions")
        layout.addWidget(self.record_button)
        return toolbar

    def _create_error_banner(self) -> QFrame:
        frame = QFrame()
        self.error_banner_frame = frame
        frame.setProperty("card", True)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(SPACE.compact, SPACE.tight, SPACE.compact, SPACE.tight)
        layout.setSpacing(SPACE.compact)
        self.error_banner = QLabel("")
        self.error_banner.setProperty("role", "muted")
        self.error_banner.setWordWrap(True)
        layout.addWidget(self.error_banner, stretch=1)
        self.error_clear_button = QPushButton("CLEAR")
        self.error_clear_button.clicked.connect(frame.hide)
        layout.addWidget(self.error_clear_button)
        frame.hide()
        return frame

    def _create_live_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, SPACE.compact, 0, 0)
        layout.setSpacing(SPACE.normal)

        self.main_splitter = CapsuleSplitter()
        self.vibration_view = VibrationView()
        vibration_card, self.vibration_container_layout = _card(
            "3-Axis Vibration",
            self.vibration_view.header_actions,
        )
        self.vibration_container_layout.addWidget(self.vibration_view, stretch=1)
        self.main_splitter.addWidget(vibration_card)

        self.right_splitter = CapsuleSplitter(Qt.Orientation.Vertical)
        orientation_card, self.orientation_container_layout = _card(
            ORIENTATION_SENSOR_LABEL
        )
        self.orientation_view = OrientationView()
        self.orientation_container_layout.addWidget(self.orientation_view, stretch=1)
        attitude_card, self.attitude_container_layout = _card(
            "Attitude & Acceleration"
        )
        self.attitude_view = AttitudeView()
        self.attitude_container_layout.addWidget(self.attitude_view, stretch=1)
        self.right_splitter.addWidget(orientation_card)
        self.right_splitter.addWidget(attitude_card)
        self.right_splitter.setStretchFactor(0, 5)
        self.right_splitter.setStretchFactor(1, 4)
        self.right_splitter.setSizes(list(_RIGHT_SPLIT_SIZES))
        self.main_splitter.addWidget(self.right_splitter)
        self.main_splitter.setStretchFactor(0, 7)
        self.main_splitter.setStretchFactor(1, 3)
        self.main_splitter.setSizes(list(_MAIN_SPLIT_SIZES))
        layout.addWidget(self.main_splitter, stretch=1)

        health_card, self.health_container_layout = _card("Stream Health")
        health_card.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.health_metrics_layout = QHBoxLayout()
        self.health_metrics_layout.setContentsMargins(0, 0, 0, 0)
        self.health_metrics_layout.setSpacing(SPACE.compact)
        self.health_field_layouts: list[QVBoxLayout] = []
        self.health_value_labels: dict[str, QLabel] = {}
        health_fields = (
            ("sample_rate", "SAMPLES/S", "—"),
            ("crc_errors", "CRC ERR", "0"),
            ("sequence_gaps", "SEQ GAP", "0"),
            ("source_drops", "SOURCE DROP", "0"),
            ("transport_drops", "TRANSPORT DROP", "0"),
            ("physical_errors", "LINK ERR", "0"),
            ("live_drops", "LIVE DROP", "0"),
            ("uptime", "UPTIME", "—"),
        )
        for key, title, initial_value in health_fields:
            field = QFrame()
            field_layout = QVBoxLayout(field)
            field_layout.setContentsMargins(
                SPACE.compact,
                SPACE.tight,
                SPACE.compact,
                SPACE.tight,
            )
            field_layout.setSpacing(SPACE.tight)
            title_label = QLabel(title)
            title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            title_label.setProperty("role", "health-label")
            value_label = QLabel(initial_value)
            value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            value_label.setProperty("role", "metric")
            field_layout.addWidget(title_label)
            field_layout.addWidget(value_label)
            self.health_metrics_layout.addWidget(field, stretch=1)
            self.health_field_layouts.append(field_layout)
            self.health_value_labels[key] = value_label
        self.health_container_layout.addLayout(self.health_metrics_layout)
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
        layout.setContentsMargins(0, SPACE.section, 0, 0)
        layout.setSpacing(SPACE.normal)
        layout.addWidget(view)
        return tab

    def _emit_connect_requested(self) -> None:
        if self._connected:
            self.disconnect_requested.emit()
            return
        if self.transport_mode_combo.currentText() == "WI-FI":
            try:
                config = self.wifi_panel.server_config()
            except ValueError as error:
                self.console_view.append_error(str(error))
                return
            self.wifi_start_requested.emit(config)
            return
        device_id = str(self.device_combo.currentData() or "")
        if device_id:
            self.connect_requested.emit(device_id)

    def _emit_watermark_requested(self) -> None:
        watermark = self.watermark_combo.currentData()
        if watermark is not None:
            self.watermark_requested.emit(int(watermark))

    def _emit_livestream_requested(self, target: str) -> None:
        self._pending_livestream_target = target
        QTimer.singleShot(
            _LIVESTREAM_SYNC_GRACE_MS,
            lambda requested_target=target: self._finish_livestream_sync_grace(
                requested_target
            ),
        )
        self.livestream_requested.emit(target)

    def _finish_livestream_sync_grace(self, requested_target: str) -> None:
        if self._pending_livestream_target == requested_target:
            self._pending_livestream_target = None

    def _update_transport_mode(self) -> None:
        is_wifi = self.transport_mode_combo.currentText() == "WI-FI"
        self.device_combo.setHidden(is_wifi)
        self.wifi_panel.setHidden(not is_wifi)
        self.connect_button.setToolTip(
            "Start/stop the Wi-Fi listener and its connections"
            if is_wifi else "Connect/disconnect the selected serial device"
        )
