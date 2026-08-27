from sensor_host.presentation.main_window import MainWindow


def test_disconnected_window_disables_stream_controls(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    window.set_connected(False)

    assert window.connect_button.isEnabled()
    assert not window.disconnect_button.isEnabled()
    assert not window.pause_button.isEnabled()
    assert not window.record_button.isEnabled()
    assert window.connection_badge.text() == "DISCONNECTED"
