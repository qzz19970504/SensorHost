"""PyQt presentation layer for the sensor host."""

from .main_window import MainWindow
from .orientation_view import AttitudeView, OrientationView
from .theme import COLORS, dark_stylesheet
from .vibration_view import VibrationView

__all__ = [
    "AttitudeView",
    "COLORS",
    "MainWindow",
    "OrientationView",
    "VibrationView",
    "dark_stylesheet",
]
