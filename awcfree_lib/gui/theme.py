"""Palette, fonts and stylesheet for the control panel.

Dark, and not by fashion: the window sits next to a keyboard you are looking at,
often in a dim room, and a bright UI destroys your sense of what the keys are
actually doing.  Everything here is tuned so the brightest thing on screen is the
rendering of the hardware itself.
"""
from __future__ import annotations

from PyQt6.QtGui import QColor, QFont, QFontDatabase

# --- palette ----------------------------------------------------------------
BG = QColor("#08090e")
BG_RAISED = QColor("#0e1017")
PANEL = QColor(255, 255, 255, 10)
PANEL_LINE = QColor(255, 255, 255, 24)
PANEL_LINE_HOT = QColor(255, 255, 255, 72)

INK = QColor("#e8ecf6")
INK_DIM = QColor("#a2b2bf")
INK_FAINT = QColor("#7f929f")

ACCENT = QColor("#7ee2c4")
ACCENT_2 = QColor("#66c8d5")
OK = QColor("#2ee6a8")
DANGER = QColor("#ff4d5e")

KEY_FACE = QColor("#151821")
KEY_EDGE = QColor(255, 255, 255, 18)

RADIUS = 20
RADIUS_SM = 9


def _pick(families: list[str], fallback: str) -> str:
    available = set(QFontDatabase.families())
    for name in families:
        if name in available:
            return name
    return fallback


def ui_font(size: int = 10, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    family = _pick(
        ["Inter", "Inter Display", "SF Pro Display", "Segoe UI Variable",
         "Noto Sans", "DejaVu Sans"],
        "Sans Serif",
    )
    f = QFont(family, size)
    f.setWeight(weight)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return f


def mono_font(size: int = 9, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    family = _pick(
        ["JetBrains Mono", "Fira Code", "Cascadia Code", "Source Code Pro",
         "Noto Sans Mono", "DejaVu Sans Mono"],
        "Monospace",
    )
    f = QFont(family, size)
    f.setWeight(weight)
    return f


def rgba(c: QColor, alpha: float) -> str:
    return f"rgba({c.red()},{c.green()},{c.blue()},{alpha:.3f})"


STYLESHEET = f"""
QWidget {{
    color: {INK.name()};
    background: transparent;
}}

QToolTip {{
    background: #12141c;
    color: {INK.name()};
    border: 1px solid {rgba(PANEL_LINE, 0.5)};
    border-radius: 6px;
    padding: 6px 8px;
}}

/* --- panels --- */
QFrame#Panel {{
    background: {rgba(QColor(255,255,255), 0.035)};
    border: 1px solid {rgba(PANEL_LINE, 0.16)};
    border-radius: {RADIUS}px;
}}

QLabel#SectionTitle {{
    color: {INK_FAINT.name()};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 2px;
}}

QLabel#Hint {{
    color: {INK_FAINT.name()};
    font-size: 11px;
}}

QLabel#Brand {{
    font-size: 17px;
    font-weight: 800;
    letter-spacing: -0.5px;
}}

/* --- buttons --- */
QPushButton {{
    background: {rgba(QColor(255,255,255), 0.05)};
    border: 1px solid {rgba(PANEL_LINE, 0.16)};
    border-radius: {RADIUS_SM}px;
    padding: 9px 13px;
    font-size: 12px;
    font-weight: 600;
    color: {INK.name()};
}}
QPushButton:hover {{
    background: {rgba(QColor(255,255,255), 0.10)};
    border-color: {rgba(PANEL_LINE_HOT, 0.8)};
}}
QPushButton:pressed {{
    background: {rgba(QColor(255,255,255), 0.16)};
}}
QPushButton:disabled {{
    color: {INK_FAINT.name()};
    background: {rgba(QColor(255,255,255), 0.02)};
}}
QPushButton[accent="true"] {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {ACCENT.name()}, stop:1 {ACCENT_2.name()});
    border: none;
    color: #102820;
}}
QPushButton[accent="true"]:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #a0eed7, stop:1 #8bdde4);
}}
QPushButton[danger="true"] {{ color: {DANGER.name()}; }}
/* Checkable buttons that are on. Strong enough to read at a glance, because the
   chassis effect buttons act on whatever is ticked here and a missed toggle means
   the effect lands on the wrong surface. */
QPushButton[on="true"] {{
    border-color: {ACCENT.name()};
    background: {rgba(ACCENT, 0.34)};
    color: #102820;
}}
QPushButton[on="true"]:hover {{
    background: {rgba(ACCENT, 0.46)};
}}
QPushButton:checked {{
    border-color: {ACCENT.name()};
}}

/* --- inputs --- */
QLineEdit {{
    background: rgba(0,0,0,0.30);
    border: 1px solid {rgba(PANEL_LINE, 0.16)};
    border-radius: 8px;
    padding: 9px 10px;
    selection-background-color: {ACCENT.name()};
}}
QLineEdit:focus {{ border-color: {ACCENT.name()}; }}

QSlider::groove:horizontal {{
    height: 5px;
    border-radius: 3px;
    background: {rgba(QColor(255,255,255), 0.14)};
}}
QSlider::sub-page:horizontal {{
    height: 5px;
    border-radius: 3px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {ACCENT.name()}, stop:1 {ACCENT_2.name()});
}}
QSlider::handle:horizontal {{
    width: 15px;
    height: 15px;
    margin: -6px 0;
    border-radius: 8px;
    background: white;
    border: 1px solid white;
}}

/* --- scrolling --- */
QScrollArea {{ border: none; }}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {rgba(QColor(255,255,255), 0.16)};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {rgba(QColor(255,255,255), 0.28)}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
"""

STYLESHEET += """
QFrame#Stage {
    background: #101820;
    border: 1px solid #29353e;
    border-radius: 22px;
}
QFrame#Panel { background: #152029; border: 1px solid #2a3741; }
QLabel#Brand { font-size: 22px; font-weight: 700; }
QLabel#BrandMark { color: #7ee2c4; font-size: 34px; font-weight: 700; padding-right: 5px; }
QLabel#StageTitle { font-size: 32px; font-weight: 600; letter-spacing: -1px; }
QLabel#InspectorTitle { font-size: 23px; font-weight: 600; }
QLabel#ModeBadge { color: #a0dbc9; background: #1a302e; border: 1px solid #2b4943;
    border-radius: 10px; padding: 7px 10px; font-size: 9px; font-weight: 600; }
QTabWidget::pane { border: none; }
QTabBar::tab { background: transparent; color: #8ea3b1; padding: 12px 20px;
    border-bottom: 2px solid #29353e; font-size: 12px; font-weight: 600; }
QTabBar::tab:selected { color: #a0eed7; border-bottom: 2px solid #7ee2c4; }
QTabBar::tab:hover { color: #e8ecf6; background: #1b2832; }
QPushButton:focus, QLineEdit:focus { border: 1px solid #7ee2c4; }
QPushButton[on="true"] { color: #b1f5df; background: #24473f; border-color: #5c9e8b; }
QPushButton[on="true"]:hover { background: #2c554b; }
QComboBox { background: #101820; border: 1px solid #34434e; border-radius: 8px;
    padding: 7px 30px 7px 10px; min-height: 20px; color: #e8ecf6; }
QComboBox:focus { border-color: #7ee2c4; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView { background: #152029; color: #e8ecf6;
    border: 1px solid #34434e; selection-background-color: #24473f; }
"""

STYLESHEET += """
QLabel#MetricValue { font-size: 38px; font-weight: 600; color: #c8f8e9; }
QPushButton[nav="true"], QPushButton[nav="sub"] {
    text-align: left; padding-left: 13px; background: #101923;
    border: 1px solid #24323d; color: #a8b5c3;
}
QPushButton[nav="true"] { font-size: 13px; }
QPushButton[nav="sub"] { font-size: 11px; padding-left: 20px; }
QPushButton[nav="true"][on="true"], QPushButton[nav="sub"][on="true"] {
    color: #f1f4f8; background: #20322f; border-color: #32765d;
}
QPushButton[nav="true"]:hover, QPushButton[nav="sub"]:hover {
    color: #f1f4f8; background: #192630; border-color: #405360;
}
"""

# Layered surfaces and restrained highlights keep hardware colours prominent.
STYLESHEET += """
QFrame#Panel {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #1b2b36, stop:0.55 #15212d, stop:1 #111b28);
    border: 1px solid #324553;
}
QFrame#Stage {
    background: qradialgradient(cx:0.45, cy:0.25, radius:0.9,
        fx:0.45, fy:0.25, stop:0 #1b3440, stop:0.6 #111e2a, stop:1 #0c1420);
    border: 1px solid #3b5262;
}
QLabel#SectionTitle { color: #95bac5; }
QLabel#MetricValue { font-size: 30px; font-weight: 600; color: #c8f8e9; }
QPushButton[nav="true"][on="true"], QPushButton[nav="sub"][on="true"] {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #244a48, stop:1 #192b39);
    border: 1px solid #528c86; border-left: 3px solid #7ee2c4;
}
QCheckBox { spacing: 8px; color: #a2b2bf; }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 5px;
    border: 1px solid #526877; background: #101923; }
QCheckBox::indicator:checked { background: #7ee2c4; border-color: #b1f5df; }
"""
