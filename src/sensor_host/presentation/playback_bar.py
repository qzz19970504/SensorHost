"""Transport controls shown above the live dashboard during offline playback."""

from __future__ import annotations

from PyQt6.QtCore import QSignalBlocker, Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSlider

from sensor_host.presentation.controls import IntegratedComboBox
from sensor_host.presentation.spacing import SPACE


_SPEEDS = (0.5, 1.0, 2.0, 4.0)
_SLIDER_STEPS = 1000


def format_duration(seconds: float) -> str:
    """Format one playback duration as M:SS.d."""
    minutes, remainder = divmod(max(0.0, seconds), 60.0)
    return f"{int(minutes)}:{remainder:04.1f}"


class PlaybackBar(QFrame):
    """Expose play/pause, stop, seek and speed controls for one archive file."""

    play_toggled = pyqtSignal(bool)
    stop_requested = pyqtSignal()
    seek_requested = pyqtSignal(float)
    speed_changed = pyqtSignal(float)

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("card", True)
        self._duration_s = 0.0
        self._seeking = False
        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            SPACE.section,
            SPACE.compact,
            SPACE.section,
            SPACE.compact,
        )
        layout.setSpacing(SPACE.compact)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.file_label = QLabel("NO FILE")
        self.file_label.setProperty("role", "eyebrow")
        layout.addWidget(self.file_label)

        self.play_button = QPushButton("PLAY")
        self.play_button.setCheckable(True)
        self.play_button.setProperty("role", "primary")
        self.play_button.setAccessibleName("Play or pause playback")
        self.play_button.toggled.connect(self._on_play_toggled)
        layout.addWidget(self.play_button)

        self.stop_button = QPushButton("STOP")
        self.stop_button.setProperty("role", "danger")
        self.stop_button.setAccessibleName("Stop playback and return to live")
        self.stop_button.clicked.connect(self.stop_requested)
        layout.addWidget(self.stop_button)

        self.seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setRange(0, _SLIDER_STEPS)
        self.seek_slider.setValue(0)
        self.seek_slider.setAccessibleName("Playback position")
        self.seek_slider.sliderPressed.connect(self._on_seek_pressed)
        self.seek_slider.sliderReleased.connect(self._emit_seek)
        layout.addWidget(self.seek_slider, stretch=1)

        self.time_label = QLabel(f"{format_duration(0.0)} / {format_duration(0.0)}")
        self.time_label.setProperty("role", "muted")
        self.time_label.setMinimumWidth(120)
        layout.addWidget(self.time_label)

        speed_label = QLabel("SPEED")
        speed_label.setProperty("role", "control-label")
        layout.addWidget(speed_label)
        self.speed_combo = IntegratedComboBox()
        for speed in _SPEEDS:
            self.speed_combo.addItem(f"{speed:g}×", speed)
        self.speed_combo.setCurrentText("1×")
        self.speed_combo.setAccessibleName("Playback speed")
        self.speed_combo.currentIndexChanged.connect(self._emit_speed)
        layout.addWidget(self.speed_combo)

    def set_file_name(self, name: str) -> None:
        self.file_label.setText(name)

    def set_state(self, playing: bool, playhead_s: float, duration_s: float) -> None:
        """Reflect controller state without re-emitting user signals."""
        self._duration_s = duration_s
        blocker = QSignalBlocker(self.play_button)
        self.play_button.setChecked(playing)
        del blocker
        self.play_button.setText("PAUSE" if playing else "PLAY")
        self.time_label.setText(
            f"{format_duration(playhead_s)} / {format_duration(duration_s)}"
        )
        if self._seeking:
            return
        ratio = min(1.0, max(0.0, playhead_s / duration_s)) if duration_s > 0 else 0.0
        blocker = QSignalBlocker(self.seek_slider)
        self.seek_slider.setValue(int(round(ratio * _SLIDER_STEPS)))
        del blocker

    def _on_play_toggled(self, is_checked: bool) -> None:
        self.play_button.setText("PAUSE" if is_checked else "PLAY")
        self.play_toggled.emit(is_checked)

    def _on_seek_pressed(self) -> None:
        self._seeking = True

    def _emit_seek(self) -> None:
        self._seeking = False
        if self._duration_s <= 0.0:
            return
        self.seek_requested.emit(
            self.seek_slider.value() / float(_SLIDER_STEPS) * self._duration_s
        )

    def _emit_speed(self, _index: int) -> None:
        speed = self.speed_combo.currentData()
        if speed is not None:
            self.speed_changed.emit(float(speed))
