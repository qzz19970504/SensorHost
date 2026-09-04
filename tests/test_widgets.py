import numpy as np

from sensor_host.acquisition import UiSnapshot
from sensor_host.presentation.main_window import MainWindow
from sensor_host.presentation.console_view import ConsoleView
from sensor_host.presentation.diagnostics_view import DiagnosticsView
from sensor_host.presentation.orientation_view import AttitudeView, OrientationView
from sensor_host.presentation.spacing import SPACE
from sensor_host.presentation.theme import dark_stylesheet
from sensor_host.presentation.vibration_view import VibrationView
from sensor_host.presentation.connection_view import NetworkInterfaceInfo
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


def test_disconnected_window_disables_stream_controls(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    window.set_connected(False)

    assert window.connect_button.isEnabled()
    assert not window.disconnect_button.isEnabled()
    assert not window.pause_button.isEnabled()
    assert not window.record_button.isEnabled()
    assert window.connection_badge.text() == "DISCONNECTED"


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


def test_tabs_and_pages_have_breathing_room(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    margins = window.live_tab.layout().contentsMargins()

    assert margins.top() == SPACE.section
    assert window.live_tab.layout().spacing() == SPACE.normal
    assert "padding: 12px 24px" in dark_stylesheet()


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
