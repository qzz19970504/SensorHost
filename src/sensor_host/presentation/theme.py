"""Design tokens, fonts and Qt stylesheet for the sensor dashboard."""

from pathlib import Path

from PyQt6.QtGui import QFontDatabase

from sensor_host.presentation.spacing import SPACE

COLORS = {
    "background": "#0D1725",
    "panel": "#172538",
    "panel_alt": "#111E2E",
    "border": "#2B415A",
    "text": "#E6EDF7",
    "muted": "#8297B2",
    "cyan": "#55E2D2",
    "green": "#38D488",
    "red": "#EF5555",
    "amber": "#F0B23D",
    "blue": "#56A7FF",
}


def load_application_fonts() -> list[str]:
    """Register the Windows fonts required by isolated/offscreen Qt runtimes."""
    loaded_families: list[str] = []
    for font_path in (
        Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("C:/Windows/Fonts/consola.ttf"),
    ):
        if not font_path.exists():
            continue
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        if font_id >= 0:
            loaded_families.extend(QFontDatabase.applicationFontFamilies(font_id))
    return loaded_families


def dark_stylesheet() -> str:
    """Return the complete dark industrial Qt stylesheet."""
    return f"""
    QMainWindow, QWidget {{
        background: {COLORS['background']};
        color: {COLORS['text']};
        font-family: "Segoe UI";
        font-size: 13px;
    }}
    QFrame[card="true"] {{
        background: {COLORS['panel']};
        border: 1px solid {COLORS['border']};
        border-radius: 8px;
    }}
    QLabel {{ background: transparent; }}
    QFrame[role="card-header"] {{
        background: transparent;
        border: 0;
        border-bottom: 1px solid {COLORS['border']};
    }}
    QWidget[role="card-actions"] {{ background: transparent; }}
    QLabel[role="card-title"] {{
        background: transparent;
        color: {COLORS['text']};
        font-size: 16px;
        font-weight: 700;
    }}
    QFrame[role="title-accent"] {{
        background: {COLORS['cyan']};
        border: 0;
        border-radius: 2px;
    }}
    QFrame[role="toolbar-divider"] {{
        background: {COLORS['border']};
        border: 0;
    }}
    QLabel[role="eyebrow"] {{
        color: {COLORS['cyan']};
        font-family: "Segoe UI";
        font-size: 13px;
        font-weight: 700;
        letter-spacing: 0px;
    }}
    QLabel[role="muted"] {{ color: {COLORS['muted']}; }}
    QLabel[role="control-label"] {{
        color: {COLORS['text']};
        font-size: 13px;
    }}
    QLabel[role="metric"] {{
        color: {COLORS['text']};
        font-family: "Consolas";
        font-size: 16px;
        font-weight: 700;
    }}
    QLabel[role="metric-compact"] {{
        color: {COLORS['text']};
        font-family: "Consolas";
        font-size: 14px;
        font-weight: 700;
    }}
    QLabel[role="health-label"] {{
        color: {COLORS['muted']};
        font-size: 11px;
    }}
    QLabel[state="online"] {{ color: {COLORS['cyan']}; }}
    QLabel[state="offline"] {{ color: {COLORS['muted']}; }}
    QPushButton {{
        min-height: 32px;
        padding: 0 12px;
        border: 1px solid {COLORS['border']};
        border-radius: 6px;
        background: {COLORS['panel_alt']};
    }}
    QPushButton:hover {{ border-color: {COLORS['cyan']}; }}
    QPushButton:focus {{ border-color: {COLORS['cyan']}; }}
    QPushButton:pressed {{ background: {COLORS['border']}; }}
    QPushButton:checked {{
        color: {COLORS['cyan']};
        border-color: {COLORS['cyan']};
        background: #123D42;
    }}
    QPushButton:disabled {{
        color: {COLORS['muted']};
        border-color: {COLORS['border']};
        background: {COLORS['panel_alt']};
    }}
    QPushButton[role="primary"] {{
        color: #06121F;
        border-color: {COLORS['cyan']};
        background: {COLORS['cyan']};
        font-weight: 700;
    }}
    QPushButton[role="primary"]:disabled {{
        color: {COLORS['muted']};
        border-color: {COLORS['border']};
        background: {COLORS['panel_alt']};
        font-weight: 400;
    }}
    QPushButton[role="danger"] {{
        color: #FFFFFF;
        border-color: #A23B3B;
        background: #B83C3C;
    }}
    QPushButton[role="danger"]:disabled {{
        color: {COLORS['muted']};
        border-color: {COLORS['border']};
        background: {COLORS['panel_alt']};
    }}
    QComboBox, QLineEdit, QSpinBox {{
        min-height: 32px;
        border: 1px solid {COLORS['border']};
        border-radius: 6px;
        padding: 0 8px;
        background: {COLORS['panel_alt']};
    }}
    QComboBox:focus, QLineEdit:focus, QSpinBox:focus {{
        border-color: {COLORS['cyan']};
    }}
    QComboBox:disabled, QLineEdit:disabled, QSpinBox:disabled {{
        color: {COLORS['muted']};
        background: {COLORS['panel']};
    }}
    QComboBox {{ padding-right: 30px; }}
    QSpinBox {{ padding-right: 22px; }}
    QComboBox::drop-down {{
        subcontrol-origin: border;
        subcontrol-position: top right;
        width: 26px;
        border: 0;
        background: transparent;
    }}
    QComboBox::down-arrow {{
        image: none;
        width: 0;
        height: 0;
    }}
    QCheckBox[role="channel-toggle"] {{
        min-height: 24px;
        spacing: 5px;
        padding: 0 7px;
        color: {COLORS['muted']};
        border: 1px solid {COLORS['border']};
        border-radius: 5px;
        background: {COLORS['panel_alt']};
    }}
    QCheckBox[role="channel-toggle"]:checked {{
        color: {COLORS['text']};
    }}
    QCheckBox[role="channel-toggle"]::indicator {{
        width: 9px;
        height: 9px;
        border: 1px solid {COLORS['muted']};
        border-radius: 2px;
        background: transparent;
    }}
    QCheckBox[role="channel-toggle"]::indicator:checked {{
        border-color: {COLORS['cyan']};
        background: {COLORS['cyan']};
    }}
    QScrollArea {{ background: transparent; border: 0; }}
    QScrollArea > QWidget {{ background: transparent; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QTabWidget::pane {{ border: 0; }}
    QTabBar::tab {{
        color: {COLORS['muted']};
        padding: {SPACE.compact}px 18px;
        border-bottom: 2px solid transparent;
        font-family: "Segoe UI";
        font-weight: 700;
    }}
    QTabBar::tab:selected {{
        color: {COLORS['cyan']};
        border-bottom-color: {COLORS['cyan']};
    }}
    QSplitter::handle {{ background: transparent; }}
    """
