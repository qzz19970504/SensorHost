"""High-rate, display-bounded IIS3DWB XYZ time-domain plot."""

from __future__ import annotations

import pyqtgraph as pg
from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from sensor_host.acquisition import UiSnapshot
from sensor_host.presentation.theme import COLORS


_CURVE_WIDTH = 1.2
_GRID_ALPHA = 0.18


class VibrationView(QWidget):
    """Render a bounded snapshot without owning acquisition data or timing."""

    def __init__(self) -> None:
        super().__init__()
        self._is_paused = False
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(8)

        self.header_actions = QWidget(self)
        self.header_actions.setProperty("role", "card-actions")
        self.header_actions.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        controls = QHBoxLayout(self.header_actions)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(4)
        self.x_toggle = self._create_channel_toggle("X", True)
        self.y_toggle = self._create_channel_toggle("Y", True)
        self.z_toggle = self._create_channel_toggle("Z", True)
        controls.addWidget(self.x_toggle)
        controls.addWidget(self.y_toggle)
        controls.addWidget(self.z_toggle)
        self.auto_y_button = QPushButton("AUTO Y")
        self.auto_y_button.setCheckable(True)
        self.auto_y_button.setChecked(True)
        controls.addWidget(self.auto_y_button)
        self.paused_badge = QLabel("")
        self.paused_badge.setProperty("role", "muted")
        self.paused_badge.hide()
        controls.addWidget(self.paused_badge)

        self.plot = pg.PlotWidget(background=COLORS["panel_alt"])
        self.plot.setLabel("bottom", "TIME", units="s")
        self.plot.setLabel("left", "ACCELERATION", units="g")
        self.plot.showGrid(x=True, y=True, alpha=_GRID_ALPHA)
        self.plot.addLegend(offset=(-8, 8))
        self.plot.setMouseEnabled(x=True, y=True)
        self.plot.setToolTip(
            "Left axis auto-scales with an SI prefix (mg, µg); plotted values are raw g."
        )
        self.x_curve = self._create_curve("X", COLORS["red"])
        self.y_curve = self._create_curve("Y", COLORS["green"])
        self.z_curve = self._create_curve("Z", COLORS["blue"])
        root_layout.addWidget(self.plot, stretch=1)

        self.rate_label = QLabel("0 samples/s · 0 visible points")
        self.rate_label.setProperty("role", "muted")
        root_layout.addWidget(self.rate_label)

        self.x_toggle.toggled.connect(self.x_curve.setVisible)
        self.y_toggle.toggled.connect(self.y_curve.setVisible)
        self.z_toggle.toggled.connect(self.z_curve.setVisible)
        self.auto_y_button.toggled.connect(self._set_auto_y)

    def update_snapshot(self, snapshot: UiSnapshot) -> None:
        """Replace all three plotted curves unless display pause is active."""
        if self._is_paused:
            return
        self.x_curve.setData(snapshot.time_s, snapshot.x_g, skipFiniteCheck=True)
        self.y_curve.setData(snapshot.time_s, snapshot.y_g, skipFiniteCheck=True)
        self.z_curve.setData(snapshot.time_s, snapshot.z_g, skipFiniteCheck=True)
        self.rate_label.setText(
            f"{snapshot.sample_rate_hz:,.0f} samples/s · "
            f"{snapshot.time_s.size:,} visible points"
        )

    def set_paused(self, is_paused: bool) -> None:
        """Freeze or resume only display updates, leaving acquisition untouched."""
        self._is_paused = is_paused
        self.paused_badge.setText("DISPLAY PAUSED" if is_paused else "")
        self.paused_badge.setVisible(is_paused)

    def _create_curve(self, name: str, color: str) -> pg.PlotDataItem:
        curve = self.plot.plot(
            name=name,
            pen=pg.mkPen(color, width=_CURVE_WIDTH),
        )
        curve.setClipToView(True)
        curve.setDownsampling(auto=True, method="peak")
        return curve

    @staticmethod
    def _create_channel_toggle(name: str, is_checked: bool) -> QCheckBox:
        toggle = QCheckBox(name)
        toggle.setProperty("role", "channel-toggle")
        toggle.setChecked(is_checked)
        return toggle

    def _set_auto_y(self, is_enabled: bool) -> None:
        self.plot.enableAutoRange(axis="y", enable=is_enabled)
