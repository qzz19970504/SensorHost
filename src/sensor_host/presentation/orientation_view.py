"""JY61PL orientation rendering with an OpenGL-first, 2D fallback view."""

from __future__ import annotations

import math
import os
from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen, QPolygonF, QResizeEvent
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from sensor_host.acquisition import UiSnapshot
from sensor_host.presentation.theme import COLORS
from sensor_host.presentation.spacing import SPACE


_STALE_AFTER_S = 0.5
_COMPACT_WINDOW_HEIGHT = 800
_COMPACT_FIELD_SPACING = 2
_DEVICE_VERTICES = np.asarray(
    [
        [-1.2, -0.75, -0.18],
        [1.2, -0.75, -0.18],
        [1.2, 0.75, -0.18],
        [-1.2, 0.75, -0.18],
        [-1.2, -0.75, 0.18],
        [1.2, -0.75, 0.18],
        [1.2, 0.75, 0.18],
        [-1.2, 0.75, 0.18],
    ],
    dtype=np.float64,
)
_DEVICE_EDGES = (
    (0, 1),
    (1, 2),
    (2, 3),
    (3, 0),
    (4, 5),
    (5, 6),
    (6, 7),
    (7, 4),
    (0, 4),
    (1, 5),
    (2, 6),
    (3, 7),
)


def rotation_matrix_zyx(
    roll_deg: float,
    pitch_deg: float,
    yaw_deg: float,
) -> NDArray[np.float64]:
    """Return the local-to-world Z-Y-X Euler rotation matrix."""
    roll, pitch, yaw = np.deg2rad([roll_deg, pitch_deg, yaw_deg])
    sin_roll, cos_roll = math.sin(roll), math.cos(roll)
    sin_pitch, cos_pitch = math.sin(pitch), math.cos(pitch)
    sin_yaw, cos_yaw = math.sin(yaw), math.cos(yaw)
    rotation_x = np.asarray(
        [[1.0, 0.0, 0.0], [0.0, cos_roll, -sin_roll], [0.0, sin_roll, cos_roll]]
    )
    rotation_y = np.asarray(
        [
            [cos_pitch, 0.0, sin_pitch],
            [0.0, 1.0, 0.0],
            [-sin_pitch, 0.0, cos_pitch],
        ]
    )
    rotation_z = np.asarray(
        [[cos_yaw, -sin_yaw, 0.0], [sin_yaw, cos_yaw, 0.0], [0.0, 0.0, 1.0]]
    )
    return rotation_z @ rotation_y @ rotation_x


def world_acceleration(
    acceleration_g: Sequence[float],
    angles_deg: Sequence[float],
) -> tuple[float, float, float]:
    """Rotate a device-local acceleration vector into world coordinates."""
    if len(acceleration_g) != 3 or len(angles_deg) != 3:
        raise ValueError("acceleration and angles must each contain three values")
    rotation = rotation_matrix_zyx(*angles_deg)
    vector = rotation @ np.asarray(acceleration_g, dtype=np.float64)
    return tuple(float(value) for value in vector)


class _FallbackCanvas(QWidget):
    """Small painter-based projection used when Qt OpenGL is unavailable."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._angles = (0.0, 0.0, 0.0)
        self._acceleration = (0.0, 0.0, 0.0)
        self._has_data = False

    def set_pose(
        self,
        angles_deg: Sequence[float],
        acceleration_world_g: Sequence[float],
        has_data: bool,
    ) -> None:
        self._angles = tuple(float(value) for value in angles_deg)
        self._acceleration = tuple(float(value) for value in acceleration_world_g)
        self._has_data = has_data
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API name
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(COLORS["panel_alt"]))
        center = QPointF(self.width() / 2.0, self.height() / 2.0)
        scale = min(self.width(), self.height()) * 0.24
        rotation = rotation_matrix_zyx(*self._angles)
        corners = np.asarray(
            [[-1.2, -0.75, 0.0], [1.2, -0.75, 0.0], [1.2, 0.75, 0.0], [-1.2, 0.75, 0.0]]
        )
        rotated = (rotation @ corners.T).T
        projected = QPolygonF(
            [QPointF(center.x() + point[0] * scale, center.y() - point[2] * scale - point[1] * scale * 0.35) for point in rotated]
        )
        painter.setPen(QPen(QColor(COLORS["cyan"]), 2.0))
        painter.setBrush(QColor(30, 85, 92, 130))
        painter.drawPolygon(projected)
        forward = rotation @ np.asarray([1.6, 0.0, 0.0])
        painter.setPen(QPen(QColor(COLORS["green"]), 3.0))
        painter.drawLine(
            center,
            QPointF(center.x() + forward[0] * scale, center.y() - forward[2] * scale - forward[1] * scale * 0.35),
        )
        acceleration = np.asarray(self._acceleration)
        if np.linalg.norm(acceleration) > 1e-6:
            painter.setPen(QPen(QColor(COLORS["amber"]), 3.0))
            painter.drawLine(
                center,
                QPointF(center.x() + acceleration[0] * scale, center.y() - acceleration[2] * scale - acceleration[1] * scale * 0.35),
            )
        if not self._has_data:
            painter.setPen(QColor(COLORS["muted"]))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "WAITING FOR JY61PL DATA")


class OrientationView(QFrame):
    """Render device pose and local acceleration without implying position."""

    def __init__(self, force_fallback: bool = False) -> None:
        super().__init__()
        self.using_opengl = False
        self.fallback_reason: str | None = None
        self._gl = None
        self._device_item = None
        self._forward_item = None
        self._acceleration_item = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE.compact)
        status_row = QHBoxLayout()
        status_row.setSpacing(SPACE.compact)
        self.mode_label = QLabel()
        self.mode_label.setProperty("role", "eyebrow")
        self.status_label = QLabel("WAITING")
        self.status_label.setProperty("role", "muted")
        status_row.addWidget(self.mode_label)
        status_row.addStretch(1)
        status_row.addWidget(self.status_label)
        layout.addLayout(status_row)

        if force_fallback:
            self.fallback_reason = "forced by caller"
            self._install_fallback(layout)
        elif os.environ.get("QT_QPA_PLATFORM", "").lower() == "offscreen":
            self.fallback_reason = "offscreen Qt platform"
            self._install_fallback(layout)
        else:
            try:
                self._install_opengl(layout)
            except (ImportError, RuntimeError) as error:
                self.fallback_reason = str(error)
                self._install_fallback(layout)
        self.mode_label.setToolTip(self.fallback_reason or "OpenGL 3D rendering active")
        self.status_label.setToolTip(
            "Orientation pose and world acceleration; not a position estimate."
        )

    def _install_fallback(self, layout: QVBoxLayout) -> None:
        self.using_opengl = False
        self.mode_label.setText("2D FALLBACK")
        self.canvas = _FallbackCanvas()
        layout.addWidget(self.canvas, stretch=1)

    def _install_opengl(self, layout: QVBoxLayout) -> None:
        import pyqtgraph.opengl as gl

        self._gl = gl
        self.gl_view = gl.GLViewWidget()
        self.gl_view.setCameraPosition(distance=7.5, elevation=22, azimuth=-45)
        grid = gl.GLGridItem()
        grid.setSize(8, 8)
        grid.setSpacing(1, 1)
        self.gl_view.addItem(grid)
        axes = (
            ([0, 0, 0], [2.5, 0, 0], (0.94, 0.33, 0.33, 1.0)),
            ([0, 0, 0], [0, 2.5, 0], (0.22, 0.83, 0.53, 1.0)),
            ([0, 0, 0], [0, 0, 2.5], (0.34, 0.65, 1.0, 1.0)),
        )
        for start, end, color in axes:
            self.gl_view.addItem(gl.GLLinePlotItem(pos=np.asarray([start, end]), color=color, width=2, antialias=True))
        self._device_item = gl.GLLinePlotItem(color=(0.33, 0.89, 0.82, 1.0), width=2, antialias=True, mode="lines")
        self._forward_item = gl.GLLinePlotItem(color=(0.22, 0.83, 0.53, 1.0), width=4, antialias=True)
        self._acceleration_item = gl.GLLinePlotItem(color=(0.94, 0.70, 0.24, 1.0), width=4, antialias=True)
        self.gl_view.addItem(self._device_item)
        self.gl_view.addItem(self._forward_item)
        self.gl_view.addItem(self._acceleration_item)
        self.using_opengl = True
        self.mode_label.setText("OPENGL 3D")
        layout.addWidget(self.gl_view, stretch=1)
        self._set_pose((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), False)

    def update_snapshot(self, snapshot: UiSnapshot) -> None:
        """Apply the newest JY61PL pose, or report waiting/stale state."""
        sample = snapshot.orientation
        if sample is None:
            self.status_label.setText("WAITING")
            self._set_pose((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), False)
            return
        age_s = snapshot.orientation_age_s
        stale = age_s is None or age_s > _STALE_AFTER_S
        self.status_label.setText("STALE" if stale else "LIVE")
        acceleration_world = world_acceleration(sample.acceleration_g, sample.angles_deg)
        self._set_pose(sample.angles_deg, acceleration_world, True)

    def set_paused(self, is_paused: bool) -> None:
        """Flag the frozen display state without implying live pose data."""
        if is_paused:
            self.status_label.setText("DISPLAY PAUSED")

    def set_offline(self) -> None:
        """Mark the pose not live after a disconnect, retaining the last pose."""
        self.status_label.setText("OFFLINE")

    def _set_pose(
        self,
        angles_deg: Sequence[float],
        acceleration_world_g: Sequence[float],
        has_data: bool,
    ) -> None:
        if not self.using_opengl:
            self.canvas.set_pose(angles_deg, acceleration_world_g, has_data)
            return
        rotation = rotation_matrix_zyx(*angles_deg)
        rotated = (rotation @ _DEVICE_VERTICES.T).T
        edge_points = np.asarray([rotated[index] for edge in _DEVICE_EDGES for index in edge])
        forward = rotation @ np.asarray([1.8, 0.0, 0.0])
        acceleration = np.asarray(acceleration_world_g, dtype=np.float64)
        self._device_item.setData(pos=edge_points)
        self._forward_item.setData(pos=np.asarray([[0.0, 0.0, 0.0], forward]))
        self._acceleration_item.setData(pos=np.asarray([[0.0, 0.0, 0.0], acceleration]))


class AttitudeView(QFrame):
    """Show the numeric JY61PL channels alongside the orientation renderer."""

    _FIELDS = (
        ("roll", "ROLL", "deg"),
        ("pitch", "PITCH", "deg"),
        ("yaw", "YAW", "deg"),
        ("acc_x", "ACC X", "g"),
        ("acc_y", "ACC Y", "g"),
        ("acc_z", "ACC Z", "g"),
        ("magnitude", "|ACC|", "g"),
        ("temperature", "TEMP", "°C"),
    )

    def __init__(self) -> None:
        super().__init__()
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(SPACE.normal)
        layout.setVerticalSpacing(SPACE.tight)
        self._grid = layout
        self._is_compact = False
        self._field_widgets: list[QFrame] = []
        self._title_labels: list[QLabel] = []
        self.value_labels: dict[str, QLabel] = {}
        for index, (key, title, unit) in enumerate(self._FIELDS):
            row, column = divmod(index, 2)
            field = QFrame()
            field_layout = QVBoxLayout(field)
            field_layout.setContentsMargins(
                SPACE.compact,
                0,
                SPACE.compact,
                0,
            )
            field_layout.setSpacing(SPACE.tight)
            title_label = QLabel(f"{title} · {unit}")
            title_label.setProperty("role", "muted")
            value_label = QLabel("—")
            value_label.setProperty("role", "metric")
            field_layout.addWidget(title_label)
            field_layout.addWidget(value_label)
            layout.addWidget(field, row, column)
            self._field_widgets.append(field)
            self._title_labels.append(title_label)
            self.value_labels[key] = value_label

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt API name
        super().resizeEvent(event)
        is_compact = self.window().height() < _COMPACT_WINDOW_HEIGHT
        if is_compact == self._is_compact:
            return
        self._apply_layout(is_compact)

    def _apply_layout(self, is_compact: bool) -> None:
        self._is_compact = is_compact
        column_count = 4 if is_compact else 2
        horizontal_spacing = SPACE.tight if is_compact else SPACE.normal
        field_horizontal_margin = SPACE.tight if is_compact else SPACE.compact
        field_spacing = _COMPACT_FIELD_SPACING if is_compact else SPACE.tight
        title_role = "health-label" if is_compact else "muted"
        value_role = "metric-compact" if is_compact else "metric"

        self._grid.setHorizontalSpacing(horizontal_spacing)
        for index, field in enumerate(self._field_widgets):
            row, column = divmod(index, column_count)
            self._grid.addWidget(field, row, column)
            field.layout().setContentsMargins(
                field_horizontal_margin,
                0,
                field_horizontal_margin,
                0,
            )
            field.layout().setSpacing(field_spacing)
            self._set_label_role(self._title_labels[index], title_role)
            key = self._FIELDS[index][0]
            self._set_label_role(self.value_labels[key], value_role)
        self.updateGeometry()

    @staticmethod
    def _set_label_role(label: QLabel, role: str) -> None:
        label.setProperty("role", role)
        label.style().unpolish(label)
        label.style().polish(label)

    def update_snapshot(self, snapshot: UiSnapshot) -> None:
        """Update numeric attitude metrics from the latest sample."""
        sample = snapshot.orientation
        if sample is None:
            for label in self.value_labels.values():
                label.setText("—")
            return
        roll, pitch, yaw = sample.angles_deg
        acc_x, acc_y, acc_z = sample.acceleration_g
        values = {
            "roll": roll,
            "pitch": pitch,
            "yaw": yaw,
            "acc_x": acc_x,
            "acc_y": acc_y,
            "acc_z": acc_z,
            "magnitude": float(np.linalg.norm(sample.acceleration_g)),
            "temperature": sample.temperature_c,
        }
        for key, value in values.items():
            self.value_labels[key].setText(f"{value:+.2f}")
