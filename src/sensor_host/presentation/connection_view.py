"""Connection configuration and multi-node navigation widgets."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import QSettings, Qt, pyqtSignal
from PyQt6.QtNetwork import QAbstractSocket, QNetworkInterface
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from sensor_host.acquisition import ConnectionState, NodeSummary
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
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE.section, SPACE.section, SPACE.section, SPACE.section)
        layout.setSpacing(SPACE.compact)
        heading = QLabel("WI-FI FIELD MODE")
        heading.setProperty("role", "eyebrow")
        layout.addWidget(heading)
        layout.addWidget(QLabel("PHONE HOTSPOT INTERFACE"))
        self.interface_combo = QComboBox()
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


class NodeSidebar(QFrame):
    """Show all logical nodes and select the target used by detail controls."""

    node_selected = pyqtSignal(str)
    alias_requested = pyqtSignal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("card", True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE.section, SPACE.section, SPACE.section, SPACE.section)
        layout.setSpacing(SPACE.compact)
        heading = QLabel("DEVICES")
        heading.setProperty("role", "eyebrow")
        layout.addWidget(heading)
        self.node_list = QListWidget()
        self.node_list.currentItemChanged.connect(self._emit_selected_node)
        layout.addWidget(self.node_list, stretch=1)
        self.alias_edit = QLineEdit()
        self.alias_edit.setPlaceholderText("Selected node alias")
        layout.addWidget(self.alias_edit)
        self.save_alias_button = QPushButton("SAVE ALIAS")
        self.save_alias_button.clicked.connect(self._emit_alias_requested)
        layout.addWidget(self.save_alias_button)

    def set_nodes(self, nodes: list[NodeSummary]) -> None:
        """Replace list content while retaining the selected node identifier."""
        selected_item = self.node_list.currentItem()
        node_id_role = Qt.ItemDataRole.UserRole
        alias_role = int(Qt.ItemDataRole.UserRole) + 1
        connected_role = int(Qt.ItemDataRole.UserRole) + 2
        selected_node_id = selected_item.data(node_id_role) if selected_item else None
        self.node_list.clear()
        for node in nodes:
            state = node.connection_state.value.upper()
            uuid_suffix = str(node.device_uuid)[-8:] if node.device_uuid else "PENDING"
            recording = " · REC" if node.is_recording else ""
            alert = " · !" if node.alert else ""
            self.node_list.addItem(
                f"{node.alias}\n{uuid_suffix} · {node.peer}\n{state}{recording}{alert}"
            )
            item = self.node_list.item(self.node_list.count() - 1)
            item.setData(node_id_role, node.node_id)
            item.setData(alias_role, node.alias)
            item.setData(
                connected_role,
                node.connection_state
                in {ConnectionState.CONNECTED, ConnectionState.STREAMING},
            )
            if node.node_id == selected_node_id:
                self.node_list.setCurrentItem(item)
        if self.node_list.currentItem() is None and self.node_list.count():
            self.node_list.setCurrentRow(0)

    def _emit_selected_node(self, current: object, _previous: object) -> None:
        if current is None:
            self.alias_edit.clear()
            return
        node_id = str(current.data(Qt.ItemDataRole.UserRole))
        alias_role = int(Qt.ItemDataRole.UserRole) + 1
        connected_role = int(Qt.ItemDataRole.UserRole) + 2
        self.alias_edit.setText(str(current.data(alias_role)))
        if current.data(connected_role):
            self.node_selected.emit(node_id)

    def _emit_alias_requested(self) -> None:
        item = self.node_list.currentItem()
        if item is not None:
            self.alias_requested.emit(
                str(item.data(Qt.ItemDataRole.UserRole)), self.alias_edit.text()
            )
