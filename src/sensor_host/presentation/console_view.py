"""Bounded line-oriented firmware CLI console."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QColor, QTextCharFormat
from PyQt6.QtWidgets import QHBoxLayout, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from sensor_host.presentation.theme import COLORS
from sensor_host.presentation.spacing import SPACE


class ConsoleView(QWidget):
    """Display a bounded CLI transcript and submit trimmed commands."""

    command_submitted = pyqtSignal(str)

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
        layout.addWidget(self.transcript, stretch=1)
        input_row = QHBoxLayout()
        input_row.setSpacing(SPACE.compact)
        self.command_input = QLineEdit()
        self.command_input.setPlaceholderText("status | acq start | acq stop | acq watermark 256")
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
        character_format = QTextCharFormat()
        character_format.setForeground(QColor(color))
        self.transcript.setCurrentCharFormat(character_format)
        self.transcript.appendPlainText(f"[{category}] {message}")
