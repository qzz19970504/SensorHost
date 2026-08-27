"""PyQt presentation layer for the sensor host."""

from .main_window import MainWindow
from .theme import COLORS, dark_stylesheet
from .vibration_view import VibrationView

__all__ = ["COLORS", "MainWindow", "VibrationView", "dark_stylesheet"]
