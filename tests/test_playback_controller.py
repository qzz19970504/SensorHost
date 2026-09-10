from __future__ import annotations

import time
from pathlib import Path

import pytest
from PyQt6.QtCore import QCoreApplication

from sensor_host.presentation.playback_controller import PlaybackController
from sensor_host.storage.archive_library import build_playback_index

from test_archive_library import write_archive


@pytest.fixture
def controller(qtbot, tmp_path: Path) -> PlaybackController:
    del qtbot  # ensures a QApplication exists for the playback timer
    playback = PlaybackController(lambda: 10.0)
    playback.load(tmp_path / "export.sdf1", build_playback_index(write_archive(tmp_path / "export.sdf1")))
    return playback


def test_load_reports_duration_and_idle_state(qtbot, tmp_path) -> None:
    playback = PlaybackController(lambda: 10.0)
    states: list[tuple[bool, float, float]] = []
    playback.state_changed.connect(lambda *args: states.append(tuple(args)))

    path = write_archive(tmp_path / "export.sdf1")
    playback.load(path, build_playback_index(path))

    assert playback.duration_s == pytest.approx(3.0)
    assert not playback.is_playing
    assert states[-1][0] is False
    assert states[-1][2] == pytest.approx(3.0)


def test_seek_fills_window_and_emits_snapshot(qtbot, controller) -> None:
    snapshots = []
    controller.snapshot_ready.connect(snapshots.append)

    controller.seek(3.0)

    snapshot = snapshots[-1]
    assert snapshot.time_s.size == 12
    assert snapshot.orientation is not None
    assert snapshot.sample_rate_hz > 0.0


def test_seek_window_excludes_later_frames(qtbot, controller) -> None:
    snapshots = []
    controller.snapshot_ready.connect(snapshots.append)

    controller.seek(1.0)

    assert snapshots[-1].time_s.size == 6
    assert snapshots[-1].orientation is None


def test_play_at_speed_reaches_end_and_pauses(qtbot, controller) -> None:
    controller.set_speed(4.0)
    controller.play()
    assert controller.is_playing

    deadline = time.monotonic() + 5.0
    while controller.is_playing and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.01)

    assert not controller.is_playing
    assert controller.playhead_s == pytest.approx(3.0, abs=0.25)


def test_play_from_end_restarts(qtbot, controller) -> None:
    controller.seek(3.0)
    controller.play()
    assert controller.playhead_s < 1.0
    controller.pause()
    assert not controller.is_playing


def test_stop_discards_decoded_history(qtbot, controller) -> None:
    snapshots = []
    controller.snapshot_ready.connect(snapshots.append)

    controller.seek(1.0)
    assert snapshots[-1].time_s.size == 6
    controller.stop()
    controller.seek(0.0)

    assert snapshots[-1].time_s.size == 3


def test_invalid_speed_is_rejected(qtbot, controller) -> None:
    with pytest.raises(ValueError):
        controller.set_speed(3.0)
