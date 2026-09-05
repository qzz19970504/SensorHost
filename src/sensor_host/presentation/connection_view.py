"""Connection configuration and multi-node navigation widgets."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import QSettings, QSignalBlocker, Qt, pyqtSignal
from PyQt6.QtNetwork import QAbstractSocket, QNetworkInterface
from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from sensor_host.acquisition import ConnectionState, NodeSummary
from sensor_host.presentation.controls import IntegratedComboBox
from sensor_host.presentation.spacing import SPACE
from sensor_host.transport import DEFAULT_TCP_PORT, DEFAULT_UDP_PORT, WifiServerConfig


@dataclass(frozen=True)
class NetworkInterfaceInfo:
    """Describe one active non-loopback IPv4 interface for field mode."""

    name: str
    ipv4: str
    netmask: str

    @property
    def label(self) -> str:
        return f"{self.name} — {self.ipv4}/{self.netmask}"


def discover_ipv4_interfaces() -> list[NetworkInterfaceInfo]:
    """Return active non-loopback IPv4 interfaces reported by Qt."""
    discovered: list[NetworkInterfaceInfo] = []
    required_flags = (
        QNetworkInterface.InterfaceFlag.IsUp
        | QNetworkInterface.InterfaceFlag.IsRunning
    )
    for interface in QNetworkInterface.allInterfaces():
        if interface.flags() & required_flags != required_flags:
            continue
        for entry in interface.addressEntries():
            address = entry.ip()
            if address.protocol() != QAbstractSocket.NetworkLayerProtocol.IPv4Protocol:
                continue
            if address.isLoopback() or address.isLinkLocal():
                continue
            netmask = entry.netmask().toString()
            if not netmask:
                continue
            discovered.append(
                NetworkInterfaceInfo(
                    name=interface.humanReadableName() or interface.name(),
                    ipv4=address.toString(),
                    netmask=netmask,
                )
            )
    return sorted(discovered, key=lambda item: (item.name, item.ipv4))


class WifiConnectionPanel(QFrame):
    """Collect and validate settings for the PC-side gateway listener."""

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("card", True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.form_scroll_area = QScrollArea()
        self.form_scroll_area.setWidgetResizable(True)
        self.form_scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(SPACE.section, SPACE.section, SPACE.section, SPACE.section)
        layout.setSpacing(SPACE.compact)
        heading = QLabel("WI-FI FIELD MODE")
        heading.setProperty("role", "eyebrow")
        layout.addWidget(heading)
        layout.addWidget(QLabel("PHONE HOTSPOT INTERFACE"))
        self.interface_combo = IntegratedComboBox()
        self.interface_combo.currentIndexChanged.connect(self._copy_selected_ipv4)
        layout.addWidget(self.interface_combo)
        layout.addWidget(QLabel("PC IPv4 PRESET IN ESP FIRMWARE"))
        self.expected_ipv4_edit = QLineEdit()
        self.expected_ipv4_edit.setPlaceholderText("Example: 192.168.43.100")
        layout.addWidget(self.expected_ipv4_edit)
        layout.addWidget(QLabel("TCP LISTEN PORT"))
        self.tcp_port_spin = QSpinBox()
        self.tcp_port_spin.setRange(1, 65_535)
        self.tcp_port_spin.setValue(DEFAULT_TCP_PORT)
        layout.addWidget(self.tcp_port_spin)
        layout.addWidget(QLabel("UDP WAKE PORT"))
        self.udp_port_spin = QSpinBox()
        self.udp_port_spin.setRange(1, 65_535)
        self.udp_port_spin.setValue(DEFAULT_UDP_PORT)
        layout.addWidget(self.udp_port_spin)
        layout.addWidget(QLabel("OPTIONAL ESP IPv4 TARGETS"))
        self.wake_targets_edit = QLineEdit()
        self.wake_targets_edit.setPlaceholderText("192.168.43.20, 192.168.43.21")
        layout.addWidget(self.wake_targets_edit)
        guidance = QLabel(
            "PC and every ESP must join the same phone hotspot. The selected PC IPv4 "
            "must match the address compiled into each ESP. If no gateway connects, "
            "check hotspot client isolation and allow inbound TCP in Windows Firewall."
        )
        guidance.setWordWrap(True)
        guidance.setProperty("role", "muted")
        layout.addWidget(guidance)
        layout.addStretch(1)
        self.form_scroll_area.setWidget(container)
        outer.addWidget(self.form_scroll_area)

    def set_network_interfaces(self, interfaces: list[NetworkInterfaceInfo]) -> None:
        """Replace selectable network interfaces while retaining the current IP."""
        selected_ipv4 = self._selected_interface_ipv4()
        self.interface_combo.clear()
        for interface in interfaces:
            self.interface_combo.addItem(interface.label, interface)
        if not interfaces:
            self.interface_combo.addItem("No active IPv4 interfaces", None)
        for item_index in range(self.interface_combo.count()):
            item = self.interface_combo.itemData(item_index)
            if isinstance(item, NetworkInterfaceInfo) and item.ipv4 == selected_ipv4:
                self.interface_combo.setCurrentIndex(item_index)
                break
        self._copy_selected_ipv4()

    def server_config(self) -> WifiServerConfig:
        """Build a validated immutable server configuration from current fields."""
        interface = self.interface_combo.currentData()
        if not isinstance(interface, NetworkInterfaceInfo):
            raise ValueError("select an active non-loopback IPv4 interface")
        targets = tuple(
            value.strip()
            for value in self.wake_targets_edit.text().split(",")
            if value.strip()
        )
        return WifiServerConfig(
            local_ipv4=interface.ipv4,
            netmask=interface.netmask,
            expected_pc_ipv4=self.expected_ipv4_edit.text().strip(),
            tcp_port=self.tcp_port_spin.value(),
            udp_port=self.udp_port_spin.value(),
            unicast_targets=targets,
        )

    def restore_settings(self, settings: QSettings) -> None:
        """Restore the last successfully started field-network profile."""
        selected_ipv4 = settings.value("wifi/local_ipv4", "", type=str)
        for item_index in range(self.interface_combo.count()):
            interface = self.interface_combo.itemData(item_index)
            if isinstance(interface, NetworkInterfaceInfo) and interface.ipv4 == selected_ipv4:
                self.interface_combo.setCurrentIndex(item_index)
                break
        expected_ipv4 = settings.value("wifi/expected_pc_ipv4", "", type=str)
        if expected_ipv4:
            self.expected_ipv4_edit.setText(expected_ipv4)
        self.tcp_port_spin.setValue(
            settings.value("wifi/tcp_port", DEFAULT_TCP_PORT, type=int)
        )
        self.udp_port_spin.setValue(
            settings.value("wifi/udp_port", DEFAULT_UDP_PORT, type=int)
        )
        targets = settings.value("wifi/unicast_targets", [])
        if isinstance(targets, str):
            targets = [targets] if targets else []
        self.wake_targets_edit.setText(", ".join(str(target) for target in targets))

    def _selected_interface_ipv4(self) -> str:
        interface = self.interface_combo.currentData()
        return interface.ipv4 if isinstance(interface, NetworkInterfaceInfo) else ""

    def _copy_selected_ipv4(self) -> None:
        if not self.expected_ipv4_edit.text().strip():
            self.expected_ipv4_edit.setText(self._selected_interface_ipv4())


_NODE_ID_ROLE = int(Qt.ItemDataRole.UserRole)
_ALIAS_ROLE = _NODE_ID_ROLE + 1
_CONNECTED_ROLE = _NODE_ID_ROLE + 2
_UUID_ROLE = _NODE_ID_ROLE + 3
_ONLINE_STATES = {ConnectionState.CONNECTED, ConnectionState.STREAMING}


class NodeSidebar(QFrame):
    """Show all logical nodes and select the target used by detail controls."""

    node_selected = pyqtSignal(str)
    alias_requested = pyqtSignal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("card", True)
        self._selected_node_id: str | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE.section, SPACE.section, SPACE.section, SPACE.section)
        layout.setSpacing(SPACE.compact)
        heading = QLabel("DEVICES")
        heading.setProperty("role", "eyebrow")
        layout.addWidget(heading)
        self.target_label = QLabel("TARGET —")
        self.target_label.setProperty("role", "muted")
        self.target_label.setWordWrap(True)
        layout.addWidget(self.target_label)
        self.node_list = QListWidget()
        self.node_list.currentItemChanged.connect(self._emit_selected_node)
        layout.addWidget(self.node_list, stretch=1)
        self.alias_edit = QLineEdit()
        self.alias_edit.setPlaceholderText("Selected node alias")
        layout.addWidget(self.alias_edit)
        self.save_alias_button = QPushButton("SAVE ALIAS")
        self.save_alias_button.clicked.connect(self._emit_alias_requested)
        layout.addWidget(self.save_alias_button)

    @property
    def selected_node_id(self) -> str | None:
        """Return the online node the highlight currently targets."""
        return self._selected_node_id

    def set_nodes(self, nodes: list[NodeSummary]) -> None:
        """Replace list content while retaining the online command target."""
        previous_id = self._selected_node_id
        if previous_id is None:
            current_item = self.node_list.currentItem()
            if current_item is not None:
                previous_id = current_item.data(_NODE_ID_ROLE)
        # Rebuild silently so a refresh never re-issues a selection command.
        blocker = QSignalBlocker(self.node_list)
        self.node_list.clear()
        first_online_row = -1
        restore_row = -1
        for row, node in enumerate(nodes):
            state = node.connection_state.value.upper()
            uuid_suffix = str(node.device_uuid)[-8:] if node.device_uuid else "PENDING"
            recording = " · REC" if node.is_recording else ""
            alert = " · !" if node.alert else ""
            self.node_list.addItem(
                f"{node.alias}\n{uuid_suffix} · {node.peer}\n{state}{recording}{alert}"
            )
            item = self.node_list.item(row)
            item.setData(_NODE_ID_ROLE, node.node_id)
            item.setData(_ALIAS_ROLE, node.alias)
            item.setData(_UUID_ROLE, uuid_suffix)
            is_online = node.connection_state in _ONLINE_STATES
            item.setData(_CONNECTED_ROLE, is_online)
            if is_online:
                if first_online_row < 0:
                    first_online_row = row
                if node.node_id == previous_id:
                    restore_row = row
            else:
                # Offline rows stay readable but can never become the command
                # target, so the highlight always matches the routed node.
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self.node_list.setCurrentRow(restore_row if restore_row >= 0 else first_online_row)
        del blocker
        self._apply_current_target(emit=False)

    def set_selected_node(self, node_id: str) -> None:
        """Reflect the controller's authoritative target without re-emitting."""
        blocker = QSignalBlocker(self.node_list)
        row = self._row_for_node_id(node_id)
        self.node_list.setCurrentRow(row if row >= 0 and self._is_row_online(row) else -1)
        del blocker
        self._apply_current_target(emit=False)

    def _emit_selected_node(self, current: object, _previous: object) -> None:
        if current is not None and not current.data(_CONNECTED_ROLE):
            # Defensive: an offline row must never become the command target.
            blocker = QSignalBlocker(self.node_list)
            self.node_list.setCurrentRow(self._row_for_node_id(self._selected_node_id))
            del blocker
            self._apply_current_target(emit=False)
            return
        self._apply_current_target(emit=True)

    def _apply_current_target(self, *, emit: bool) -> None:
        item = self.node_list.currentItem()
        if item is None or not item.data(_CONNECTED_ROLE):
            self._selected_node_id = None
            self.alias_edit.clear()
            self.target_label.setText("TARGET —")
            return
        alias = str(item.data(_ALIAS_ROLE))
        uuid_suffix = str(item.data(_UUID_ROLE))
        self._selected_node_id = str(item.data(_NODE_ID_ROLE))
        self.alias_edit.setText(alias)
        self.target_label.setText(f"TARGET {alias} · {uuid_suffix}")
        if emit:
            self.node_selected.emit(self._selected_node_id)

    def _row_for_node_id(self, node_id: str | None) -> int:
        if not node_id:
            return -1
        for row in range(self.node_list.count()):
            if self.node_list.item(row).data(_NODE_ID_ROLE) == node_id:
                return row
        return -1

    def _is_row_online(self, row: int) -> bool:
        item = self.node_list.item(row)
        return bool(item is not None and item.data(_CONNECTED_ROLE))

    def _emit_alias_requested(self) -> None:
        item = self.node_list.currentItem()
        if item is not None:
            self.alias_requested.emit(
                str(item.data(_NODE_ID_ROLE)), self.alias_edit.text()
            )
