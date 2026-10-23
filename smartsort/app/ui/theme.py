"""Application palettes and stylesheet generation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    name: str
    background: str
    surface: str
    surface_alt: str
    sidebar: str
    border: str
    text: str
    text_muted: str
    accent: str
    accent_hover: str
    accent_soft: str
    danger: str
    warning: str
    success: str
    is_dark: bool


LIGHT = Palette(
    name="light",
    background="#f5f6f8",
    surface="#ffffff",
    surface_alt="#f0f2f5",
    sidebar="#ffffff",
    border="#e3e6ea",
    text="#1a1d23",
    text_muted="#6b7280",
    accent="#2563eb",
    accent_hover="#1d4ed8",
    accent_soft="#e8effd",
    danger="#dc2626",
    warning="#b45309",
    success="#15803d",
    is_dark=False,
)

DARK = Palette(
    name="dark",
    background="#15171c",
    surface="#1e2129",
    surface_alt="#262a33",
    sidebar="#191c22",
    border="#2c313b",
    text="#e8eaee",
    text_muted="#98a1ae",
    accent="#4f8cff",
    accent_hover="#6b9dff",
    accent_soft="#1e2a44",
    danger="#f87171",
    warning="#fbbf24",
    success="#4ade80",
    is_dark=True,
)

PALETTES = {"light": LIGHT, "dark": DARK}


def palette_for(name: str) -> Palette:
    return PALETTES.get(name, LIGHT)


def stylesheet(p: Palette) -> str:
    return f"""
    QWidget {{
        background: transparent;
        color: {p.text};
        font-family: "Segoe UI", "Tahoma", "Noto Sans Arabic", sans-serif;
        font-size: 10pt;
    }}
    QMainWindow, QDialog {{
        background: {p.background};
    }}
    #root {{
        background: {p.background};
    }}
    #sidebar {{
        background: {p.sidebar};
        border-right: 1px solid {p.border};
    }}
    #brandName {{
        font-size: 15pt;
        font-weight: 700;
        color: {p.text};
    }}
    #brandTag {{
        font-size: 8pt;
        color: {p.text_muted};
    }}
    QPushButton#navButton {{
        text-align: left;
        padding: 9px 12px;
        border: none;
        border-radius: 8px;
        color: {p.text_muted};
        font-size: 10pt;
        background: transparent;
    }}
    QPushButton#navButton:hover {{
        background: {p.surface_alt};
        color: {p.text};
    }}
    QPushButton#navButton:checked {{
        background: {p.accent_soft};
        color: {p.accent};
        font-weight: 600;
    }}
    #pageTitle {{
        font-size: 19pt;
        font-weight: 700;
        color: {p.text};
    }}
    #pageSubtitle {{
        font-size: 9.5pt;
        color: {p.text_muted};
    }}
    #sectionTitle {{
        font-size: 10pt;
        font-weight: 600;
        color: {p.text};
    }}
    #muted {{
        color: {p.text_muted};
        font-size: 9pt;
    }}
    #card {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: 12px;
    }}
    #statValue {{
        font-size: 20pt;
        font-weight: 700;
        color: {p.text};
    }}
    #statCaption {{
        font-size: 8.5pt;
        color: {p.text_muted};
    }}
    QPushButton {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: 8px;
        padding: 7px 14px;
        color: {p.text};
    }}
    QPushButton:hover {{
        background: {p.surface_alt};
    }}
    QPushButton:disabled {{
        color: {p.text_muted};
        background: {p.surface_alt};
    }}
    QPushButton#primary {{
        background: {p.accent};
        color: #ffffff;
        border: 1px solid {p.accent};
        font-weight: 600;
    }}
    QPushButton#primary:hover {{
        background: {p.accent_hover};
        border-color: {p.accent_hover};
    }}
    QPushButton#primary:disabled {{
        background: {p.surface_alt};
        border-color: {p.border};
        color: {p.text_muted};
    }}
    QPushButton#danger {{
        color: {p.danger};
        border: 1px solid {p.danger};
        background: transparent;
    }}
    QPushButton#danger:hover {{
        background: {p.surface_alt};
    }}
    QPushButton#link {{
        border: none;
        background: transparent;
        color: {p.accent};
        padding: 2px 4px;
    }}
    QPushButton#link:hover {{
        text-decoration: underline;
    }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: 8px;
        padding: 6px 9px;
        selection-background-color: {p.accent};
        selection-color: #ffffff;
        min-height: 20px;
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
        border: 1px solid {p.accent};
    }}
    QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
        color: {p.text_muted};
        background: {p.surface_alt};
        border-color: {p.border};
    }}
    QSpinBox, QDoubleSpinBox {{
        padding-right: 22px;
    }}
    QSpinBox::up-button, QDoubleSpinBox::up-button {{
        subcontrol-origin: border;
        subcontrol-position: top right;
        width: 18px;
        border: none;
        border-top-right-radius: 8px;
        background: transparent;
    }}
    QSpinBox::down-button, QDoubleSpinBox::down-button {{
        subcontrol-origin: border;
        subcontrol-position: bottom right;
        width: 18px;
        border: none;
        border-bottom-right-radius: 8px;
        background: transparent;
    }}
    QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
    QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
        background: {p.surface_alt};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 18px;
    }}
    QComboBox QAbstractItemView {{
        background: {p.surface};
        border: 1px solid {p.border};
        selection-background-color: {p.accent_soft};
        selection-color: {p.text};
        outline: none;
    }}
    QTableWidget, QTableView {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: 10px;
        gridline-color: {p.border};
        selection-background-color: {p.accent_soft};
        selection-color: {p.text};
        alternate-background-color: {p.surface_alt};
    }}
    QHeaderView::section {{
        background: {p.surface_alt};
        color: {p.text_muted};
        border: none;
        border-bottom: 1px solid {p.border};
        padding: 7px 8px;
        font-size: 9pt;
        font-weight: 600;
    }}
    QTableWidget::item {{
        padding: 6px 8px;
        border: none;
    }}
    QScrollArea {{
        border: none;
        background: transparent;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {p.border};
        border-radius: 5px;
        min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {p.text_muted};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 10px;
        margin: 2px;
    }}
    QScrollBar::handle:horizontal {{
        background: {p.border};
        border-radius: 5px;
        min-width: 30px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0px;
    }}
    QCheckBox {{
        spacing: 8px;
    }}
    QCheckBox::indicator {{
        width: 17px;
        height: 17px;
        border-radius: 5px;
        border: 1px solid {p.border};
        background: {p.surface};
    }}
    QCheckBox::indicator:checked {{
        background: {p.accent};
        border-color: {p.accent};
        image: none;
    }}
    QCheckBox::indicator:checked:disabled {{
        background: {p.border};
        border-color: {p.border};
    }}
    QCheckBox::indicator:disabled {{
        background: {p.surface_alt};
    }}
    QMenu {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: 8px;
        padding: 4px;
    }}
    QMenu::item {{
        padding: 7px 22px 7px 14px;
        border-radius: 6px;
    }}
    QMenu::item:selected {{
        background: {p.accent_soft};
        color: {p.text};
    }}
    QToolTip {{
        background: {p.surface};
        color: {p.text};
        border: 1px solid {p.border};
        padding: 5px;
        border-radius: 6px;
    }}
    #statusBarLabel {{
        color: {p.text_muted};
        font-size: 8.5pt;
    }}
    QSplitter::handle {{
        background: transparent;
        height: 8px;
    }}
    """


STATUS_COLORS = {
    "organized": ("success", "#15803d", "#dcfce7"),
    "failed": ("danger", "#b91c1c", "#fee2e2"),
    "skipped": ("muted", "#6b7280", "#eef0f3"),
    "duplicate": ("muted", "#6b7280", "#eef0f3"),
    "undone": ("warning", "#b45309", "#fef3c7"),
}


def pill_colors(status: str, p: Palette) -> tuple[str, str]:
    """Return (foreground, background) for a status pill."""
    if p.is_dark:
        mapping = {
            "organized": ("#86efac", "#14361f"),
            "failed": ("#fca5a5", "#3a1717"),
            "skipped": ("#9aa3af", "#2a2e36"),
            "duplicate": ("#9aa3af", "#2a2e36"),
            "undone": ("#fcd34d", "#3a2c10"),
        }
    else:
        mapping = {
            "organized": ("#15803d", "#dcfce7"),
            "failed": ("#b91c1c", "#fee2e2"),
            "skipped": ("#5b6472", "#eef0f3"),
            "duplicate": ("#5b6472", "#eef0f3"),
            "undone": ("#b45309", "#fef3c7"),
        }
    return mapping.get(status, mapping["skipped"])
