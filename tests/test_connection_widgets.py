import uuid

import pytest
from PyQt6.QtCore import QSettings, Qt

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


def test_offline_node_cannot_become_command_target(qtbot) -> None:
    sidebar = NodeSidebar()
    qtbot.addWidget(sidebar)
    offline = NodeSummary(
        node_id="wifi-a",
        transport_kind=TransportKind.WIFI,
        peer="192.168.43.20:5000",
        connection_state=ConnectionState.RECONNECTING,
        alias="A",
    )
    online = NodeSummary(
        node_id="wifi-b",
        transport_kind=TransportKind.WIFI,
        peer="192.168.43.21:5000",
        connection_state=ConnectionState.STREAMING,
        device_uuid=uuid.UUID("00112233-4455-6677-8899-aabbccddeeff"),
        alias="B",
    )
    selected: list[str] = []
    sidebar.node_selected.connect(selected.append)
    node_id_role = int(Qt.ItemDataRole.UserRole)

    sidebar.set_nodes([offline, online])

    # The online node stays the visible target even though the offline row sorts
    # first; before the fix the offline row kept the highlight (target mismatch).
    assert sidebar.node_list.currentItem().data(node_id_role) == "wifi-b"
    assert sidebar.selected_node_id == "wifi-b"
    assert selected == []

    # Clicking the offline row must not move the highlight or the target.
    sidebar.node_list.setCurrentRow(0)
    assert sidebar.node_list.currentItem().data(node_id_role) == "wifi-b"
    assert sidebar.selected_node_id == "wifi-b"
    assert "wifi-a" not in selected


def test_set_selected_node_writes_back_target_without_reemitting(qtbot) -> None:
    sidebar = NodeSidebar()
    qtbot.addWidget(sidebar)
    first = NodeSummary(
        node_id="wifi-a",
        transport_kind=TransportKind.WIFI,
        peer="192.168.43.20:5000",
        connection_state=ConnectionState.STREAMING,
        device_uuid=uuid.UUID("550e8400-e29b-41d4-a716-446655440000"),
        alias="A",
    )
    second = NodeSummary(
        node_id="wifi-b",
        transport_kind=TransportKind.WIFI,
        peer="192.168.43.21:5000",
        connection_state=ConnectionState.STREAMING,
        device_uuid=uuid.UUID("00112233-4455-6677-8899-aabbccddeeff"),
        alias="B",
    )
    selected: list[str] = []
    sidebar.node_selected.connect(selected.append)
    node_id_role = int(Qt.ItemDataRole.UserRole)

    sidebar.set_nodes([first, second])
    assert sidebar.selected_node_id == "wifi-a"
    assert selected == []

    sidebar.set_selected_node("wifi-b")
    assert sidebar.selected_node_id == "wifi-b"
    assert sidebar.node_list.currentItem().data(node_id_role) == "wifi-b"
    assert selected == []
    assert "B" in sidebar.target_label.text()

    sidebar.set_selected_node("")
    assert sidebar.selected_node_id is None
    assert sidebar.node_list.currentItem() is None
    assert sidebar.target_label.text() == "TARGET —"


def test_wifi_form_scrolls_when_height_is_constrained(qtbot) -> None:
    panel = WifiConnectionPanel()
    qtbot.addWidget(panel)
    panel.set_network_interfaces(
        [NetworkInterfaceInfo("Phone Hotspot", "192.168.43.100", "255.255.255.0")]
    )
    panel.resize(300, 220)
    panel.show()
    qtbot.wait(20)

    # The form is taller than the constrained panel, so every field stays
    # reachable through the scroll area instead of being clipped.
    assert panel.form_scroll_area.verticalScrollBar().maximum() > 0
    assert panel.form_scroll_area.horizontalScrollBar().maximum() == 0
    assert panel.server_config().tcp_port == 54321


def test_unsaved_alias_draft_survives_node_refresh(qtbot) -> None:
    sidebar = NodeSidebar()
    qtbot.addWidget(sidebar)
    node = NodeSummary(
        node_id="wifi-a",
        transport_kind=TransportKind.WIFI,
        peer="192.168.43.20:5000",
        connection_state=ConnectionState.STREAMING,
        device_uuid=uuid.UUID("550e8400-e29b-41d4-a716-446655440000"),
        alias="A",
    )
    sidebar.set_nodes([node])
    sidebar.alias_edit.setText("Draft Name")

    sidebar.set_nodes([node])

    assert sidebar.alias_edit.text() == "Draft Name"


def test_save_alias_disabled_without_valid_length(qtbot) -> None:
    sidebar = NodeSidebar()
    qtbot.addWidget(sidebar)
    node = NodeSummary(
        node_id="wifi-a",
        transport_kind=TransportKind.WIFI,
        peer="192.168.43.20:5000",
        connection_state=ConnectionState.STREAMING,
        alias="A",
    )
    sidebar.set_nodes([node])
    assert sidebar.save_alias_button.isEnabled()

    sidebar.alias_edit.clear()
    assert not sidebar.save_alias_button.isEnabled()

    sidebar.alias_edit.setText("x" * 65)
    assert not sidebar.save_alias_button.isEnabled()
