import numpy as np

from sensor_host.acquisition import UiSnapshot
from sensor_host.presentation.main_window import MainWindow
from sensor_host.presentation.vibration_view import VibrationView
from sensor_host.protocol import ParserStats


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
