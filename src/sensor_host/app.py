"""Application composition root for the PyQt sensor host."""

from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from sensor_host.presentation import MainWindow, dark_stylesheet


def main() -> int:
    """Create, show, and run the sensor host application."""
    application = QApplication(sys.argv)
    application.setApplicationName("STM32 Sensor Host")
    application.setStyleSheet(dark_stylesheet())
    window = MainWindow()
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
