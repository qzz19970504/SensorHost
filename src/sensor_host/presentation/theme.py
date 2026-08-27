"""Design tokens and Qt stylesheet for the sensor dashboard."""

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


def dark_stylesheet() -> str:
    """Return the complete dark industrial Qt stylesheet."""
    return f"""
    QMainWindow, QWidget {{
        background: {COLORS['background']};
        color: {COLORS['text']};
        font-family: "Segoe UI", "Microsoft YaHei UI";
        font-size: 12px;
    }}
    QFrame[card="true"] {{
        background: {COLORS['panel']};
        border: 1px solid {COLORS['border']};
        border-radius: 8px;
    }}
    QLabel[role="eyebrow"] {{
        color: {COLORS['cyan']};
        font-family: "Consolas";
        font-weight: 700;
        letter-spacing: 2px;
    }}
    QLabel[role="muted"] {{ color: {COLORS['muted']}; }}
    QLabel[state="online"] {{ color: {COLORS['cyan']}; }}
    QLabel[state="offline"] {{ color: {COLORS['muted']}; }}
    QPushButton {{
        min-height: 30px;
        padding: 0 12px;
        border: 1px solid {COLORS['border']};
        border-radius: 6px;
        background: {COLORS['panel_alt']};
    }}
    QPushButton:hover {{ border-color: {COLORS['cyan']}; }}
    QPushButton:checked {{
        color: {COLORS['cyan']};
        border-color: {COLORS['cyan']};
        background: #123D42;
    }}
    QPushButton:disabled {{
        color: {COLORS['muted']};
        background: {COLORS['panel_alt']};
    }}
    QPushButton[role="danger"] {{
        color: #FFFFFF;
        border-color: #A23B3B;
        background: #B83C3C;
    }}
    QComboBox, QLineEdit {{
        min-height: 30px;
        border: 1px solid {COLORS['border']};
        border-radius: 6px;
        padding: 0 8px;
        background: {COLORS['panel_alt']};
    }}
    QTabWidget::pane {{ border: 0; }}
    QTabBar::tab {{
        color: {COLORS['muted']};
        padding: 10px 20px;
        border-bottom: 2px solid transparent;
        font-family: "Consolas";
        font-weight: 700;
    }}
    QTabBar::tab:selected {{
        color: {COLORS['cyan']};
        border-bottom-color: {COLORS['cyan']};
    }}
    QSplitter::handle {{ background: transparent; width: 6px; height: 6px; }}
    """
