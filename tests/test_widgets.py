from dataclasses import replace

import numpy as np
from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtWidgets import QFrame, QLabel

from sensor_host.acquisition import (
    AcquisitionHealth,
    ConnectionState,
    NodeSummary,
    TransportKind,
    UiSnapshot,
)
from sensor_host.presentation.controls import IntegratedComboBox
from sensor_host.presentation.main_window import MainWindow
from sensor_host.presentation.console_view import ConsoleView
from sensor_host.presentation.diagnostics_view import DiagnosticsView
from sensor_host.presentation.orientation_view import AttitudeView, OrientationView
from sensor_host.presentation.spacing import SPACE
from sensor_host.presentation.theme import dark_stylesheet, load_application_fonts
from sensor_host.presentation.vibration_view import VibrationView
from sensor_host.presentation.connection_view import (
    NetworkInterfaceInfo,
    WifiConnectionPanel,
)
from sensor_host.protocol import FirmwareControlState, ParserStats


def make_snapshot(
    time_s: list[float],
    x_g: list[float],
    y_g: list[float],
    z_g: list[float],
) -> UiSnapshot:
    return UiSnapshot(
        time_s=np.asarray(time_s, dtype=np.float64),
        x_g=np.asarray(x_g, dtype=np.float64),
        y_g=np.asarray(y_g, dtype=np.float64),
        z_g=np.asarray(z_g, dtype=np.float64),
        orientation=None,
        orientation_age_s=None,
        firmware_status=None,
        parser_stats=ParserStats(),
        sample_rate_hz=0.0,
    )


def online_node(node_id: str = "wifi-1") -> NodeSummary:
    return NodeSummary(
        node_id=node_id,
        transport_kind=TransportKind.WIFI,
        peer="192.168.43.20:5000",
        connection_state=ConnectionState.STREAMING,
        alias="North Motor",
    )


def test_disconnected_window_disables_stream_controls(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    window.set_connected(False)

    assert window.connect_button.isEnabled()
    assert not window.disconnect_button.isEnabled()
    assert not window.pause_button.isEnabled()
    assert not window.record_button.isEnabled()
    assert not window.live_target_combo.isEnabled()
    assert not window.start_button.isEnabled()
    assert not window.stop_button.isEnabled()
    assert window.connection_badge.text() == "DISCONNECTED"


def test_connected_window_enables_acquisition_controls(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    window.set_connected(True)
    window.set_nodes([online_node()])

    assert window.live_target_combo.isEnabled()
    assert window.live_target_combo.currentText() == "UART"
    assert window.start_button.isEnabled()
    assert window.stop_button.isEnabled()


def test_start_button_emits_start_request(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.set_connected(True)
    window.set_nodes([online_node()])

    with qtbot.waitSignal(window.start_requested):
        window.start_button.click()


def test_stop_button_emits_stop_request(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.set_connected(True)
    window.set_nodes([online_node()])

    with qtbot.waitSignal(window.stop_requested):
        window.stop_button.click()


def test_operator_live_target_change_emits_request(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.set_connected(True)

    with qtbot.waitSignal(window.livestream_requested) as signal:
        window.live_target_combo.setCurrentText("CDC")

    assert signal.args == ["CDC"]


def test_stale_snapshot_does_not_revert_a_pending_live_target(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.set_connected(True)
    stale_snapshot = replace(
        make_snapshot([], [], [], []),
        firmware_control_state=FirmwareControlState(livestream_target="UART"),
    )

    window.live_target_combo.setCurrentText("CDC")
    window.update_snapshot(stale_snapshot)

    assert window.live_target_combo.currentText() == "CDC"


def test_snapshot_live_target_update_does_not_emit_request(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    requested_targets: list[str] = []
    window.livestream_requested.connect(requested_targets.append)
    snapshot = replace(
        make_snapshot([], [], [], []),
        firmware_control_state=FirmwareControlState(livestream_target="CDC"),
    )

    window.update_snapshot(snapshot)

    assert window.live_target_combo.currentText() == "CDC"
    assert requested_targets == []


def test_window_switches_between_cdc_and_wifi_connection_controls(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.set_network_interfaces(
        [NetworkInterfaceInfo("Phone Hotspot", "192.168.43.100", "255.255.255.0")]
    )

    window.transport_mode_combo.setCurrentText("WI-FI")

    assert window.device_combo.isHidden()
    assert not window.wifi_panel.isHidden()
    assert window.connect_button.text() == "START LISTENER"


def test_window_emits_validated_wifi_configuration(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.set_network_interfaces(
        [NetworkInterfaceInfo("Phone Hotspot", "192.168.43.100", "255.255.255.0")]
    )
    window.transport_mode_combo.setCurrentText("WI-FI")

    with qtbot.waitSignal(window.wifi_start_requested) as signal:
        window.connect_button.click()

    assert signal.args[0].local_ipv4 == "192.168.43.100"
    assert signal.args[0].tcp_port == 54321


def test_live_dashboard_uses_balanced_splitters_and_health_metrics(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(1440, 900)
    window.show()
    qtbot.wait(20)

    assert set(window.health_value_labels) == {
        "sample_rate",
        "crc_errors",
        "sequence_gaps",
        "source_drops",
        "transport_drops",
        "physical_errors",
        "live_drops",
        "uptime",
    }
    assert all(
        label.property("role") == "metric"
        for label in window.health_value_labels.values()
    )
    main_sizes = window.main_splitter.sizes()
    right_sizes = window.right_splitter.sizes()
    assert main_sizes[0] / main_sizes[1] >= 2.0
    assert 1.1 <= right_sizes[0] / right_sizes[1] <= 1.5


def test_attitude_metrics_use_readable_two_column_grid(qtbot) -> None:
    view = AttitudeView()
    qtbot.addWidget(view)
    layout = view.layout()

    columns = [layout.getItemPosition(index)[1] for index in range(layout.count())]

    assert max(columns) == 1
    assert all(
        label.property("role") == "metric" for label in view.value_labels.values()
    )


def test_vibration_view_updates_three_curves_and_axis_units(qtbot) -> None:
    view = VibrationView()
    qtbot.addWidget(view)
    snapshot = make_snapshot(
        time_s=[-1.0, 0.0],
        x_g=[1.0, 2.0],
        y_g=[3.0, 4.0],
        z_g=[5.0, 6.0],
    )

    view.update_snapshot(snapshot)

    assert view.x_curve.getData()[1].tolist() == [1.0, 2.0]
    assert view.y_curve.getData()[1].tolist() == [3.0, 4.0]
    assert view.z_curve.getData()[1].tolist() == [5.0, 6.0]
    assert view.plot.getAxis("bottom").labelText == "TIME"
    assert view.plot.getAxis("left").labelUnits == "g"


def test_vibration_pause_freezes_display_data(qtbot) -> None:
    view = VibrationView()
    qtbot.addWidget(view)
    initial = make_snapshot([-1.0, 0.0], [1.0, 2.0], [3.0, 4.0], [5.0, 6.0])
    replacement = make_snapshot([0.0], [9.0], [9.0], [9.0])
    view.update_snapshot(initial)

    view.set_paused(True)
    view.update_snapshot(replacement)

    assert view.x_curve.getData()[1].tolist() == [1.0, 2.0]
    assert view.paused_badge.text() == "DISPLAY PAUSED"


def test_orientation_view_can_force_fallback(qtbot) -> None:
    view = OrientationView(force_fallback=True)
    qtbot.addWidget(view)

    assert view.using_opengl is False
    assert "2D" in view.mode_label.text()


def test_console_bounds_transcript_and_emits_trimmed_command(qtbot) -> None:
    console = ConsoleView(max_blocks=100)
    qtbot.addWidget(console)

    with qtbot.waitSignal(console.command_submitted) as signal:
        console.command_input.setText(" status ")
        console.send_button.click()

    assert signal.args == ["status"]
    for index in range(150):
        console.append_local(f"line {index}")
    assert console.transcript.document().blockCount() <= 100


def test_balanced_spacing_tokens_are_stable() -> None:
    assert (
        SPACE.tight,
        SPACE.compact,
        SPACE.normal,
        SPACE.section,
        SPACE.major,
    ) == (4, 8, 12, 16, 24)


def test_tabs_are_compact_without_crowding_live_content(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    margins = window.live_tab.layout().contentsMargins()

    assert window.tabs.tabBar().height() == 38
    assert margins.top() == SPACE.compact
    assert window.live_tab.layout().spacing() == SPACE.normal
    assert "padding: 8px 18px" in dark_stylesheet()


def test_card_and_metric_spacing_is_balanced(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    card_margins = window.vibration_container_layout.contentsMargins()
    assert card_margins.left() == SPACE.section
    assert window.vibration_container_layout.spacing() == SPACE.section
    assert window.health_metrics_layout.spacing() == SPACE.compact
    assert all(
        layout.spacing() == SPACE.tight for layout in window.health_field_layouts
    )


def test_live_cards_use_article_style_titles_and_accents(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    expected_titles = {
        "3-Axis Vibration",
        "JY61PL Orientation",
        "Attitude & Acceleration",
        "Stream Health",
    }
    title_labels = {
        label.text(): label
        for label in window.live_tab.findChildren(QLabel)
        if label.property("role") == "card-title"
    }
    title_accents = [
        frame
        for frame in window.live_tab.findChildren(QFrame)
        if frame.property("role") == "title-accent"
    ]

    assert set(title_labels) == expected_titles
    assert len(title_accents) == len(expected_titles)
    assert all(accent.minimumWidth() == 3 for accent in title_accents)
    assert all(accent.minimumHeight() == 20 for accent in title_accents)


def test_acquisition_toolbar_is_flat_and_vertically_centered(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(1080, 700)
    window.show()
    qtbot.wait(20)

    groups = [
        frame
        for frame in window.acquisition_toolbar.findChildren(QFrame)
        if frame.property("controlGroup") is True
    ]

    assert groups == []
    assert (
        window.acquisition_toolbar.layout().alignment()
        & Qt.AlignmentFlag.AlignVCenter
    )
    assert window.app_header.layout().alignment() & Qt.AlignmentFlag.AlignVCenter
    assert window.window_combo.minimumWidth() >= 72
    assert window.watermark_combo.minimumWidth() >= 72


def test_vibration_actions_live_in_card_header(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    actions = window.vibration_view.header_actions

    assert actions.property("role") == "card-actions"
    assert actions.parentWidget().property("role") == "card-header"
    assert window.vibration_view.layout().indexOf(actions) == -1
    assert actions.layout().indexOf(window.vibration_view.x_toggle) >= 0
    assert actions.layout().indexOf(window.vibration_view.auto_y_button) >= 0
    assert all(
        toggle.property("role") == "channel-toggle"
        for toggle in (
            window.vibration_view.x_toggle,
            window.vibration_view.y_toggle,
            window.vibration_view.z_toggle,
        )
    )


def test_combo_boxes_use_integrated_painted_chevron(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    combos = (
        window.device_combo,
        window.window_combo,
        window.watermark_combo,
    )

    assert all(isinstance(combo, IntegratedComboBox) for combo in combos)
    assert all(len(combo.arrow_points()) == 3 for combo in combos)
    assert all(
        max(point.x() for point in combo.arrow_points()) < combo.width()
        for combo in combos
    )


def test_vibration_pause_badge_only_appears_while_paused(qtbot) -> None:
    view = VibrationView()
    qtbot.addWidget(view)
    view.show()

    assert not view.paused_badge.isVisible()

    view.set_paused(True)
    assert view.paused_badge.isVisible()
    assert view.paused_badge.text() == "DISPLAY PAUSED"

    view.set_paused(False)
    assert not view.paused_badge.isVisible()


def test_splitters_keep_large_hit_area_and_balanced_proportions(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(1440, 900)
    window.show()
    qtbot.wait(20)

    assert window.main_splitter.handleWidth() == 12
    assert window.right_splitter.handleWidth() == 12
    assert window.main_splitter.handle(1).width() == 12
    assert window.right_splitter.handle(1).height() == 12
    main_sizes = window.main_splitter.sizes()
    right_sizes = window.right_splitter.sizes()
    assert main_sizes[0] / main_sizes[1] >= 2.0
    assert 1.1 <= right_sizes[0] / right_sizes[1] <= 1.5


def test_theme_does_not_expand_splitter_hit_areas(qtbot, qapp) -> None:
    original_stylesheet = qapp.styleSheet()
    qapp.setStyleSheet(dark_stylesheet())
    try:
        window = MainWindow()
        qtbot.addWidget(window)
        window.resize(1440, 900)
        window.show()
        qtbot.wait(20)

        assert window.main_splitter.handle(1).width() == 12
        assert window.right_splitter.handle(1).height() == 12
        right_sizes = window.right_splitter.sizes()
        assert 1.1 <= right_sizes[0] / right_sizes[1] <= 1.5
    finally:
        qapp.setStyleSheet(original_stylesheet)


def test_short_dashboard_reflows_attitude_metrics_without_overlap(qtbot, qapp) -> None:
    original_stylesheet = qapp.styleSheet()
    load_application_fonts()
    qapp.setStyleSheet(dark_stylesheet())
    try:
        window = MainWindow()
        qtbot.addWidget(window)
        window.resize(1080, 700)
        window.show()
        qtbot.wait(20)

        layout = window.attitude_view.layout()
        columns = [
            layout.getItemPosition(index)[1] for index in range(layout.count())
        ]
        assert max(columns) == 3
        assert all(
            label.height() >= label.sizeHint().height()
            for label in window.attitude_view.value_labels.values()
        )
    finally:
        qapp.setStyleSheet(original_stylesheet)


def test_theme_defines_transparent_labels_and_structured_card_roles() -> None:
    stylesheet = dark_stylesheet()

    assert "QLabel {" in stylesheet
    assert "background: transparent" in stylesheet
    assert 'QLabel[role="card-title"]' in stylesheet
    assert 'QFrame[role="title-accent"]' in stylesheet


def test_theme_integrates_combo_arrow_into_rounded_input() -> None:
    stylesheet = dark_stylesheet()

    assert "QComboBox::drop-down" in stylesheet
    assert "background: transparent" in stylesheet
    assert "border: 0" in stylesheet
    assert "QComboBox::down-arrow" in stylesheet
    assert 'QCheckBox[role="channel-toggle"]' in stylesheet


def test_console_and_diagnostics_pages_use_section_padding(qtbot) -> None:
    console = ConsoleView()
    diagnostics = DiagnosticsView()
    qtbot.addWidget(console)
    qtbot.addWidget(diagnostics)

    assert console.layout().spacing() == SPACE.normal
    margins = diagnostics.grid.contentsMargins()
    assert (margins.left(), margins.top()) == (SPACE.section, SPACE.section)


def test_diagnostics_exposes_latest_structured_firmware_fields(qtbot) -> None:
    view = DiagnosticsView()
    qtbot.addWidget(view)
    snapshot = make_snapshot([], [], [], [])
    snapshot = UiSnapshot(
        time_s=snapshot.time_s,
        x_g=snapshot.x_g,
        y_g=snapshot.y_g,
        z_g=snapshot.z_g,
        orientation=None,
        orientation_age_s=None,
        firmware_status=None,
        parser_stats=ParserStats(),
        sample_rate_hz=0.0,
        firmware_control_state=FirmwareControlState(
            acquisition_state="ACQUIRE",
            livestream_target="UART",
            sd_ready=True,
            diag_sd_stall_ms=12,
        ),
    )

    view.update_snapshot(snapshot)

    assert view.value_labels["acquisition_state_text"].text() == "ACQUIRE"
    assert view.value_labels["livestream_target"].text() == "UART"
    assert view.value_labels["sd_ready"].text() == "True"
    assert view.value_labels["diag_sd_stall_ms"].text() == "12"


def test_wifi_interface_combo_uses_integrated_chevron(qtbot) -> None:
    panel = WifiConnectionPanel()
    qtbot.addWidget(panel)

    assert isinstance(panel.interface_combo, IntegratedComboBox)
    assert len(panel.interface_combo.arrow_points()) == 3


def test_wifi_spinbox_matches_line_edit_input_height(qtbot, qapp) -> None:
    original = qapp.styleSheet()
    load_application_fonts()
    qapp.setStyleSheet(dark_stylesheet())
    try:
        panel = WifiConnectionPanel()
        qtbot.addWidget(panel)
        panel.show()
        qtbot.wait(20)

        spin_height = panel.tcp_port_spin.sizeHint().height()
        edit_height = panel.expected_ipv4_edit.sizeHint().height()
        # UI-10: the port spin boxes join the 32px input family and must not
        # render shorter than the neighbouring line edit (the original defect);
        # native up/down button chrome may add a couple of pixels on top.
        assert spin_height >= 32
        assert 0 <= spin_height - edit_height <= 4
    finally:
        qapp.setStyleSheet(original)


def test_primary_and_danger_roles_mark_operation_hierarchy(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.connect_button.property("role") == "primary"
    assert window.start_button.property("role") == "primary"
    assert window.stop_button.property("role") == "danger"
    assert window.disconnect_button.property("role") == "danger"


def test_theme_separates_disabled_danger_and_primary_roles() -> None:
    stylesheet = dark_stylesheet()

    assert 'QPushButton[role="danger"]:disabled' in stylesheet
    assert 'QPushButton[role="primary"]' in stylesheet
    assert 'QWidget[role="card-actions"]' in stylesheet
    assert "QSpinBox" in stylesheet


def test_display_pause_marks_frozen_views(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.set_connected(True)
    window.show()
    qtbot.wait(20)

    window.set_display_paused(True)

    assert window.vibration_view.paused_badge.isVisible()
    assert window.orientation_view.status_label.text() == "DISPLAY PAUSED"

    window.set_display_paused(False)
    assert not window.vibration_view.paused_badge.isVisible()


def test_disconnect_marks_orientation_offline_not_live(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.set_connected(True)
    window.orientation_view.status_label.setText("LIVE")

    window.set_connected(False)

    assert window.orientation_view.status_label.text() == "OFFLINE"


def test_unknown_health_counters_show_em_dash_not_zero(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    window.update_snapshot(make_snapshot([], [], [], []))

    assert window.health_value_labels["source_drops"].text() == "—"
    assert window.health_value_labels["transport_drops"].text() == "—"
    assert window.health_value_labels["physical_errors"].text() == "—"
    assert window.health_value_labels["live_drops"].text() == "—"
    # Host-side parser statistics always have evidence and keep numeric zeros.
    assert window.health_value_labels["crc_errors"].text() == "0"


def test_error_surfaces_outside_console_and_marks_unread(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(20)
    console_index = window.tabs.indexOf(window.console_tab)
    assert window.tabs.currentWidget() is window.live_tab

    window.console_view.append_error("device disconnected")

    assert window.tabs.tabText(console_index) == "CONSOLE ●"

    window.tabs.setCurrentWidget(window.console_tab)
    assert window.tabs.tabText(console_index) == "CONSOLE"


def test_hidden_diagnostics_page_defers_until_visible(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    snapshot = replace(
        make_snapshot([], [], [], []),
        firmware_control_state=FirmwareControlState(acquisition_state="ACQUIRE"),
    )

    window.update_snapshot(snapshot)
    assert window.diagnostics_view.value_labels["acquisition_state_text"].text() == "—"

    window.tabs.setCurrentWidget(window.diagnostics_tab)
    assert (
        window.diagnostics_view.value_labels["acquisition_state_text"].text()
        == "ACQUIRE"
    )


def test_error_banner_is_non_modal_and_dismissible(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(20)

    assert not window.error_banner_frame.isVisible()
    window.show_error("select a connected node")
    assert window.error_banner_frame.isVisible()
    assert "select a connected node" in window.error_banner.text()

    window.error_clear_button.click()
    assert not window.error_banner_frame.isVisible()


def test_record_button_reflects_actual_recording_sessions(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    window.set_nodes([online_node()])
    assert window.record_button.text() == "● RECORD"

    window.set_nodes([replace(online_node(), is_recording=True)])
    assert "1" in window.record_button.text()


def test_views_explain_units_and_pose_semantics(qtbot) -> None:
    vibration = VibrationView()
    qtbot.addWidget(vibration)
    assert "SI prefix" in vibration.plot.toolTip()

    orientation = OrientationView(force_fallback=True)
    qtbot.addWidget(orientation)
    assert orientation.mode_label.toolTip() == "forced by caller"
    assert "not a position" in orientation.status_label.toolTip()


def test_diagnostics_long_values_wrap_and_are_selectable(qtbot) -> None:
    view = DiagnosticsView()
    qtbot.addWidget(view)
    long_error = "e" * 300

    view.update_health(
        AcquisitionHealth(
            bytes_received=0,
            frames_received=0,
            recording_failure=None,
            last_error=long_error,
        )
    )

    label = view.value_labels["last_error"]
    assert label.text() == long_error
    assert label.wordWrap()
    assert label.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse


def test_reset_layout_restores_default_splitter_sizes(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(20)
    expected_workspace = window.workspace_splitter.sizes()
    expected_main = window.main_splitter.sizes()

    window.workspace_splitter.setSizes([80, 1300])
    window.main_splitter.setSizes([200, 1200])

    window.reset_layout_button.click()

    assert window.workspace_splitter.sizes() == expected_workspace
    assert window.main_splitter.sizes() == expected_main


def test_vibration_reset_view_restores_full_time_range(qtbot) -> None:
    view = VibrationView()
    qtbot.addWidget(view)
    view.update_snapshot(make_snapshot([-5.0, 0.0], [1, 2], [3, 4], [5, 6]))
    view_box = view.plot.getViewBox()
    view.plot.setXRange(-1.0, -0.5, padding=0)
    assert not view_box.state["autoRange"][0]

    view.reset_view_button.click()

    # Reset re-enables following the latest samples on both axes.
    assert view_box.state["autoRange"][0]
    assert view_box.state["autoRange"][1]
    assert view.auto_y_button.isChecked()


def test_console_supports_timestamps_follow_and_clear(qtbot) -> None:
    console = ConsoleView(max_blocks=100)
    qtbot.addWidget(console)

    console.append_local("hello")
    first_line = console.transcript.toPlainText().splitlines()[0]
    assert "[LOCAL] hello" in first_line
    assert first_line.count("]") >= 2  # [HH:MM:SS] [LOCAL]

    console.append_local("more")
    console.clear_display_button.click()
    assert console.transcript.toPlainText() == ""
    assert console.follow_checkbox.isChecked()


def test_form_labels_are_buddied_to_their_controls(qtbot) -> None:
    panel = WifiConnectionPanel()
    qtbot.addWidget(panel)
    panel_buddies = {label.buddy() for label in panel.findChildren(QLabel)}
    assert panel.interface_combo in panel_buddies
    assert panel.expected_ipv4_edit in panel_buddies
    assert panel.tcp_port_spin in panel_buddies

    window = MainWindow()
    qtbot.addWidget(window)
    window_buddies = {label.buddy() for label in window.findChildren(QLabel)}
    assert window.window_combo in window_buddies
    assert window.live_target_combo in window_buddies


def test_console_export_help_is_collapsible(qtbot) -> None:
    console = ConsoleView()
    qtbot.addWidget(console)

    assert console.export_help_label.isHidden()
    console.export_help_button.click()
    assert not console.export_help_label.isHidden()
    assert "AT+EXPORT" in console.export_help_label.text()


def test_console_can_show_other_node_responses_with_source(qtbot) -> None:
    console = ConsoleView()
    qtbot.addWidget(console)
    console.set_current_node("wifi-b")
    console.all_nodes_checkbox.setChecked(True)

    console.append_response_from("wifi-a", "hello from a")
    console.append_response_from("wifi-b", "selected dup")

    text = console.transcript.toPlainText()
    assert "hello from a" in text
    assert "wifi-a" in text
    assert "selected dup" not in text

    console.all_nodes_checkbox.setChecked(False)
    console.append_response_from("wifi-a", "hidden now")
    assert "hidden now" not in console.transcript.toPlainText()


def test_attitude_reflows_by_own_width(qtbot, qapp) -> None:
    original = qapp.styleSheet()
    load_application_fonts()
    qapp.setStyleSheet(dark_stylesheet())
    try:
        window = MainWindow()
        qtbot.addWidget(window)
        window.resize(1080, 700)
        window.show()
        qtbot.wait(20)
        layout = window.attitude_view.layout()
        narrow_cols = max(
            layout.getItemPosition(index)[1] for index in range(layout.count())
        )
        assert narrow_cols == 3

        window.resize(1440, 900)
        qtbot.wait(20)
        layout = window.attitude_view.layout()
        wide_cols = max(
            layout.getItemPosition(index)[1] for index in range(layout.count())
        )
        assert wide_cols == 1
    finally:
        qapp.setStyleSheet(original)


def test_keyboard_can_activate_core_controls_and_console_enter(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.set_connected(True)
    window.set_nodes([online_node()])
    window.show()
    qtbot.wait(20)

    window.start_button.setFocus()
    assert window.start_button.hasFocus()
    with qtbot.waitSignal(window.start_requested):
        qtbot.keyClick(window.start_button, Qt.Key.Key_Space)

    qtbot.keyClick(window.start_button, Qt.Key.Key_Tab)
    assert window.focusWidget() is not window.start_button

    window.tabs.setCurrentWidget(window.console_tab)
    window.console_view.command_input.setFocus()
    with qtbot.waitSignal(window.console_view.command_submitted) as signal:
        qtbot.keyClicks(window.console_view.command_input, "AT+STATE?")
        qtbot.keyClick(window.console_view.command_input, Qt.Key.Key_Return)
    assert signal.args == ["AT+STATE?"]


def test_key_controls_expose_accessible_names(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    for widget in (
        window.connect_button,
        window.disconnect_button,
        window.start_button,
        window.stop_button,
        window.pause_button,
        window.record_button,
        window.window_combo,
        window.live_target_combo,
    ):
        assert widget.accessibleName()


def test_diagnostics_search_section_jump_and_error_summary(qtbot) -> None:
    view = DiagnosticsView()
    qtbot.addWidget(view)
    view.show()
    qtbot.wait(20)

    assert view.error_summary.text() == "No active errors"
    view.update_health(
        AcquisitionHealth(
            bytes_received=0,
            frames_received=0,
            recording_failure=None,
            last_error="device disconnected",
        )
    )
    assert "device disconnected" in view.error_summary.text()

    view.section_combo.setCurrentText("FIRMWARE")
    view.search_edit.setText("crc")
    qtbot.keyClick(view.search_edit, Qt.Key.Key_Return)
    assert "device disconnected" in view.error_summary.text()


def test_stable_tab_order_across_primary_controls(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.set_connected(True)
    window.set_nodes([online_node()])
    window.show()
    qtbot.wait(20)

    # connect_button is disabled while connected, so start from refresh_button.
    window.refresh_button.setFocus()
    qtbot.keyClick(window.refresh_button, Qt.Key.Key_Tab)
    assert window.focusWidget() is window.disconnect_button

    window.start_button.setFocus()
    qtbot.keyClick(window.start_button, Qt.Key.Key_Tab)
    assert window.focusWidget() is window.stop_button


def test_layout_persists_and_reset_clears_ui_keys(qtbot, tmp_path) -> None:
    settings = QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings=settings)
    qtbot.addWidget(window)
    window.resize(1200, 800)
    window.workspace_splitter.setSizes([300, 900])
    window.save_layout()
    settings.sync()
    settings.beginGroup("ui")
    assert settings.value("window_width", 0, type=int) == 1200
    settings.endGroup()

    restored = MainWindow(settings=settings)
    qtbot.addWidget(restored)
    restored._restore_layout()
    persisted = restored.workspace_splitter.sizes()
    restored.workspace_splitter.setSizes([300, 900])
    # Restoring must reproduce exactly what setting the persisted sizes yields.
    assert persisted == restored.workspace_splitter.sizes()

    restored._reset_layout()
    settings.sync()
    settings.beginGroup("ui")
    assert settings.childKeys() == []
    settings.endGroup()
