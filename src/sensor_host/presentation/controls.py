"""Small styled controls shared by the dashboard shell."""

from __future__ import annotations

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QPaintEvent, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QComboBox

from sensor_host.presentation.theme import COLORS


class IntegratedComboBox(QComboBox):
    """Draw a stable chevron without a separately boxed drop-down subcontrol."""

    def arrow_points(self) -> tuple[QPointF, QPointF, QPointF]:
        """Return the chevron geometry in widget coordinates."""
        center_y = self.height() / 2.0
        right = self.width() - 12.0
        return (
            QPointF(right - 8.0, center_y - 2.0),
            QPointF(right - 4.0, center_y + 2.0),
            QPointF(right, center_y - 2.0),
        )

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt API name
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(COLORS["muted"]), 1.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPolyline(QPolygonF(self.arrow_points()))
