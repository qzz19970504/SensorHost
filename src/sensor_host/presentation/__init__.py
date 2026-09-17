"""PyQt presentation layer for the sensor host."""

from .main_window import MainWindow
from .orientation_view import AttitudeView, OrientationView
from .app_controller import AppController
from .console_view import ConsoleView
from .diagnostics_view import DiagnosticsView
from .ota_dialog import OtaDialog
from .theme import COLORS, dark_stylesheet, load_application_fonts
from .vibration_view import VibrationView

__all__ = [
    "AttitudeView",
    "AppController",
    "COLORS",
    "MainWindow",
    "ConsoleView",
    "DiagnosticsView",
    "OtaDialog",
    "OrientationView",
    "VibrationView",
    "dark_stylesheet",
    "load_application_fonts",
]
