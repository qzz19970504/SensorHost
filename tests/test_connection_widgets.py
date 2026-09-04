import uuid

import pytest
from PyQt6.QtCore import QSettings

from sensor_host.acquisition import ConnectionState, NodeSummary, TransportKind
from sensor_host.presentation.connection_view import (
    NetworkInterfaceInfo,
    NodeSidebar,
    WifiConnectionPanel,
)


def test_wifi_panel_builds_validated_server_configuration(qtbot) -> None:
    panel = WifiConnectionPanel()
    qtbot.addWidget(panel)
    panel.set_network_interfaces(
        [NetworkInterfaceInfo("Phone Hotspot", "192.168.43.100", "255.255.255.0")]
    )
    panel.expected_ipv4_edit.setText("192.168.43.100")
    panel.wake_targets_edit.setText("192.168.43.20, 192.168.43.21")

    config = panel.server_config()

    assert config.local_ipv4 == "192.168.43.100"
    assert config.tcp_port == 54321
    assert config.udp_port == 12345
    assert config.unicast_targets == ("192.168.43.20", "192.168.43.21")


def test_wifi_panel_surfaces_fixed_ip_mismatch(qtbot) -> None:
    panel = WifiConnectionPanel()
    qtbot.addWidget(panel)
    panel.set_network_interfaces(
        [NetworkInterfaceInfo("Phone Hotspot", "192.168.43.100", "255.255.255.0")]
    )
    panel.expected_ipv4_edit.setText("192.168.43.101")

    with pytest.raises(ValueError, match="does not match"):
        panel.server_config()


def test_wifi_panel_restores_one_or_many_unicast_targets(qtbot, tmp_path) -> None:
    settings = QSettings(str(tmp_path / "wifi.ini"), QSettings.Format.IniFormat)
    settings.setValue("wifi/unicast_targets", "192.168.43.20")
    panel = WifiConnectionPanel()
    qtbot.addWidget(panel)

    panel.restore_settings(settings)

    assert panel.wake_targets_edit.text() == "192.168.43.20"


def test_node_sidebar_emits_selected_node_and_alias(qtbot) -> None:
    sidebar = NodeSidebar()
    qtbot.addWidget(sidebar)
    device_uuid = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
    sidebar.set_nodes(
        [
            NodeSummary(
                node_id="wifi-1",
                transport_kind=TransportKind.WIFI,
                peer="192.168.43.20:5000",
                connection_state=ConnectionState.STREAMING,
                device_uuid=device_uuid,
                alias="North Motor",
                is_recording=True,
            )
        ]
    )

    with qtbot.waitSignal(sidebar.alias_requested) as signal:
        sidebar.alias_edit.setText("Pump House")
        sidebar.save_alias_button.click()

    assert signal.args == ["wifi-1", "Pump House"]
    assert "REC" in sidebar.node_list.item(0).text()


def test_node_sidebar_does_not_select_reconnecting_node(qtbot) -> None:
    sidebar = NodeSidebar()
    qtbot.addWidget(sidebar)
    selected: list[str] = []
    sidebar.node_selected.connect(selected.append)

    sidebar.set_nodes(
        [
            NodeSummary(
                node_id="wifi-old",
                transport_kind=TransportKind.WIFI,
                peer="192.168.43.20:5000",
                connection_state=ConnectionState.RECONNECTING,
                alias="North Motor",
            )
        ]
    )

    assert selected == []
