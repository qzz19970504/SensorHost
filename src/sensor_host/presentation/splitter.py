"""Splitter with a compact painted affordance inside a generous hit area."""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QSplitter, QSplitterHandle, QWidget

from sensor_host.presentation.theme import COLORS


_HANDLE_HIT_AREA = 12
_CAPSULE_THICKNESS = 4
_CAPSULE_LENGTH = 48
_CAPSULE_END_INSET = 12
_CAPSULE_RADIUS = 2


class _CapsuleSplitterHandle(QSplitterHandle):
    """Paint a centered capsule without changing the splitter hit geometry."""

    def __init__(self, orientation: Qt.Orientation, parent: QSplitter) -> None:
        super().__init__(orientation, parent)
        self._is_hovered = False

    def enterEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt API name
        self._is_hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt API name
        self._is_hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt API name
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        color_name = COLORS["cyan"] if self._is_hovered else COLORS["border"]
        painter.setBrush(QColor(color_name))
        painter.drawRoundedRect(
            self._capsule_rectangle(),
            _CAPSULE_RADIUS,
            _CAPSULE_RADIUS,
        )

    def _capsule_rectangle(self) -> QRectF:
        if self.orientation() == Qt.Orientation.Horizontal:
            capsule_length = min(
                _CAPSULE_LENGTH,
                max(_CAPSULE_THICKNESS, self.height() - 2 * _CAPSULE_END_INSET),
            )
            return QRectF(
                (self.width() - _CAPSULE_THICKNESS) / 2,
                (self.height() - capsule_length) / 2,
                _CAPSULE_THICKNESS,
                capsule_length,
            )

        capsule_length = min(
            _CAPSULE_LENGTH,
            max(_CAPSULE_THICKNESS, self.width() - 2 * _CAPSULE_END_INSET),
        )
        return QRectF(
            (self.width() - capsule_length) / 2,
            (self.height() - _CAPSULE_THICKNESS) / 2,
            capsule_length,
            _CAPSULE_THICKNESS,
        )


class CapsuleSplitter(QSplitter):
    """Provide a 12 px drag target with a centered four-pixel visual handle."""

    def __init__(
        self,
        orientation: Qt.Orientation = Qt.Orientation.Horizontal,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(orientation, parent)
        self.setHandleWidth(_HANDLE_HIT_AREA)

    def createHandle(self) -> QSplitterHandle:  # noqa: N802 - Qt API name
        """Create the custom handle used for every divider in this splitter."""
        return _CapsuleSplitterHandle(self.orientation(), self)
