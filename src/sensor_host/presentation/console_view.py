"""Bounded line-oriented firmware CLI console."""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QColor, QTextCharFormat
from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from sensor_host.presentation.theme import COLORS
from sensor_host.presentation.spacing import SPACE


class ConsoleView(QWidget):
    """Display a bounded CLI transcript and submit trimmed commands."""

    command_submitted = pyqtSignal(str)
    message_appended = pyqtSignal(str)

    def __init__(self, max_blocks: int = 2_000) -> None:
        super().__init__()
        if max_blocks <= 0:
            raise ValueError("max_blocks must be positive")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE.normal)
        self.transcript = QPlainTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.document().setMaximumBlockCount(max_blocks)
        self.transcript.setPlaceholderText("Firmware CLI responses appear here")
        controls = QHBoxLayout()
        controls.setSpacing(SPACE.compact)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search transcript")
        self.search_edit.returnPressed.connect(self._find_next)
        controls.addWidget(self.search_edit, stretch=1)
        self.follow_checkbox = QCheckBox("FOLLOW")
        self.follow_checkbox.setChecked(True)
        controls.addWidget(self.follow_checkbox)
        self.clear_display_button = QPushButton("CLEAR DISPLAY")
        self.clear_display_button.clicked.connect(self.transcript.clear)
        controls.addWidget(self.clear_display_button)
        self.export_help_button = QPushButton("EXPORT HELP")
        self.export_help_button.setCheckable(True)
        controls.addWidget(self.export_help_button)
        self.export_help_label = QLabel(
            "Manual archive export: STOP or wait for IDLE, select the node, then send "
            "AT+EXPORT=CDC or AT+EXPORT=UART and wait for EMPTY/COMPLETE/ABORTED. "
            "Files are saved under the host data root exports/ directory."
        )
        self.export_help_label.setWordWrap(True)
        self.export_help_label.setProperty("role", "muted")
        self.export_help_label.hide()
        self.export_help_button.toggled.connect(self.export_help_label.setVisible)
        layout.addLayout(controls)
        layout.addWidget(self.export_help_label)
        layout.addWidget(self.transcript, stretch=1)
        input_row = QHBoxLayout()
        input_row.setSpacing(SPACE.compact)
        self.command_input = QLineEdit()
        self.command_input.setPlaceholderText(
            "AT+STATE? | AT+START | AT+STOP | AT+LIVESTREAM? | AT+EXPORT=CDC"
        )
        self.send_button = QPushButton("SEND")
        input_row.addWidget(self.command_input, stretch=1)
        input_row.addWidget(self.send_button)
        layout.addLayout(input_row)
        self.send_button.clicked.connect(self._submit)
        self.command_input.returnPressed.connect(self._submit)

    def append_local(self, message: str) -> None:
        self._append("LOCAL", message, COLORS["muted"])

    def append_response(self, message: str) -> None:
        self._append("RX", message, COLORS["cyan"])

    def append_error(self, message: str) -> None:
        self._append("ERROR", message, COLORS["red"])

    def _submit(self) -> None:
        command = self.command_input.text().strip()
        if not command:
            return
        self._append("TX", command, COLORS["green"])
        self.command_input.clear()
        self.command_submitted.emit(command)

    def _append(self, category: str, message: str, color: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        scrollbar = self.transcript.verticalScrollBar()
        previous = scrollbar.value()
        character_format = QTextCharFormat()
        character_format.setForeground(QColor(color))
        self.transcript.setCurrentCharFormat(character_format)
        self.transcript.appendPlainText(f"[{stamp}] [{category}] {message}")
        if not self.follow_checkbox.isChecked():
            scrollbar.setValue(previous)
        self.message_appended.emit(message)

    def _find_next(self) -> None:
        text = self.search_edit.text()
        if text:
            self.transcript.find(text)
