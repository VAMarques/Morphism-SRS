from PySide6.QtWidgets import QApplication, QComboBox, QListView
from PySide6.QtGui import QPalette, QColor

DARK_THEME_QSS = """
/* ToolTip Styling */
QToolTip {
    background-color: #1e293b;
    color: #f8fafc;
    border: 1px solid #475569;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
    font-family: -apple-system, "BlinkMacSystemFont", "SF Pro Text", "Helvetica Neue", "Segoe UI", Roboto, "Ubuntu", "DejaVu Sans", "Liberation Sans", sans-serif;
}

/* Global Window & Widget Styling */
QMainWindow, QDialog {
    background-color: #0b0f19;
    color: #f8fafc;
    font-family: -apple-system, "BlinkMacSystemFont", "SF Pro Text", "Helvetica Neue", "Segoe UI", Roboto, "Ubuntu", "DejaVu Sans", "Liberation Sans", sans-serif;
}


QWidget {
    background-color: transparent;
    color: #f8fafc;
    font-family: -apple-system, "BlinkMacSystemFont", "SF Pro Text", "Helvetica Neue", "Segoe UI", Roboto, "Ubuntu", "DejaVu Sans", "Liberation Sans", sans-serif;
}


/* ToolBar & Header Styling */
QToolBar {
    background-color: #0f172a;
    border-bottom: 1px solid #1e293b;
    padding: 6px;
    spacing: 8px;
}

QToolButton {
    background-color: #1e293b;
    color: #f8fafc;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 6px 12px;
    font-size: 13px;
    font-weight: 500;
}

QToolButton:hover {
    background-color: #334155;
    border-color: #6366f1;
}

QToolButton:pressed {
    background-color: #4338ca;
}

/* Push Buttons */
QPushButton {
    background-color: #1e293b;
    color: #f8fafc;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 8px 16px;
    font-size: 14px;
    font-weight: 600;
}

QPushButton:hover {
    background-color: #334155;
    border-color: #6366f1;
}

QPushButton:pressed {
    background-color: #4338ca;
}

/* Rating Buttons in Review Window */
QPushButton#BtnShowAnswer {
    background-color: #6366f1;
    color: #ffffff;
    border: none;
    font-size: 16px;
    font-weight: bold;
    border-radius: 10px;
}

QPushButton#BtnShowAnswer:hover {
    background-color: #4f46e5;
}

QPushButton#BtnAgain {
    background-color: #991b1b;
    color: #fca5a5;
    border: 1px solid #ef4444;
}
QPushButton#BtnAgain:hover { background-color: #dc2626; color: white; }

QPushButton#BtnHard {
    background-color: #78350f;
    color: #fde68a;
    border: 1px solid #f59e0b;
}
QPushButton#BtnHard:hover { background-color: #d97706; color: white; }

QPushButton#BtnGood {
    background-color: #065f46;
    color: #a7f3d0;
    border: 1px solid #10b981;
}
QPushButton#BtnGood:hover { background-color: #059669; color: white; }

QPushButton#BtnEasy {
    background-color: #1e40af;
    color: #bfdbfe;
    border: 1px solid #3b82f6;
}
QPushButton#BtnEasy:hover { background-color: #2563eb; color: white; }

/* Control Frame */
QFrame#ControlFrame {
    background-color: #0f172a;
    border-top: 1px solid #1e293b;
    border-radius: 12px;
}

/* Inputs, Text Editors & List Widgets */
QLineEdit, QTextEdit, QListWidget, QSpinBox, QDoubleSpinBox {
    background-color: #1e293b;
    color: #f8fafc;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 6px;
    selection-background-color: #6366f1;
    selection-color: #ffffff;
}

QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: #6366f1;
}

/* Universal QComboBox & Dropdown Popup List Styling */
QComboBox {
    background-color: #1e293b;
    color: #f8fafc;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 6px 12px;
    font-size: 13px;
    font-weight: 500;
    min-width: 140px;
}

QComboBox:hover {
    border-color: #6366f1;
    background-color: #334155;
}

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 24px;
    border-left-width: 0px;
    border-top-right-radius: 8px;
    border-bottom-right-radius: 8px;
}

/* Dropdown Popup List View (QAbstractItemView / QListView) */
QComboBox QAbstractItemView, QListView {
    background-color: #1e293b !important;
    color: #f8fafc !important;
    border: 1px solid #6366f1;
    selection-background-color: #6366f1 !important;
    selection-color: #ffffff !important;
    outline: 0;
    padding: 4px;
    border-radius: 6px;
}

QComboBox QAbstractItemView::item, QListView::item {
    background-color: #1e293b !important;
    color: #f8fafc !important;
    padding: 8px 12px;
    min-height: 28px;
    border-radius: 4px;
}

QComboBox QAbstractItemView::item:hover, QComboBox QAbstractItemView::item:selected,
QListView::item:hover, QListView::item:selected {
    background-color: #6366f1 !important;
    color: #ffffff !important;
}

/* QMenu Context Menus */
QMenu {
    background-color: #1e293b;
    color: #f8fafc;
    border: 1px solid #6366f1;
    border-radius: 8px;
    padding: 6px;
}

QMenu::item {
    background-color: transparent;
    color: #f8fafc;
    padding: 8px 20px 8px 12px;
    border-radius: 4px;
}

QMenu::item:selected {
    background-color: #6366f1;
    color: #ffffff;
}

QMenu::separator {
    height: 1px;
    background-color: #334155;
    margin: 4px 0;
}

/* GroupBoxes & Labels */
QGroupBox {
    border: 1px solid #334155;
    border-radius: 10px;
    margin-top: 12px;
    font-weight: bold;
    color: #38bdf8;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 4px 8px;
}

/* Splitter */
QSplitter::handle {
    background-color: #1e293b;
}

/* Tables & Calendar */
QTableWidget, QCalendarWidget {
    background-color: #1e293b;
    color: #f8fafc;
    gridline-color: #334155;
    border: 1px solid #334155;
    border-radius: 8px;
}

QHeaderView::section {
    background-color: #0f172a;
    color: #38bdf8;
    font-weight: bold;
    padding: 6px;
    border: 1px solid #334155;
}
"""

def apply_global_dark_theme(app: QApplication):
    """
    Apply Fusion widget style, global dark QPalette, and comprehensive QSS
    to ensure all QComboBox drop-downs and popup menus render in dark mode on Windows.
    """
    app.setStyle("Fusion")

    palette = QPalette()
    dark_bg = QColor("#0b0f19")
    dark_surface = QColor("#1e293b")
    dark_header = QColor("#0f172a")
    text_color = QColor("#f8fafc")
    accent = QColor("#6366f1")

    palette.setColor(QPalette.Window, dark_bg)
    palette.setColor(QPalette.WindowText, text_color)
    palette.setColor(QPalette.Base, dark_surface)
    palette.setColor(QPalette.AlternateBase, dark_header)
    palette.setColor(QPalette.ToolTipBase, dark_surface)
    palette.setColor(QPalette.ToolTipText, text_color)

    palette.setColor(QPalette.Text, text_color)
    palette.setColor(QPalette.Button, dark_surface)
    palette.setColor(QPalette.ButtonText, text_color)
    palette.setColor(QPalette.BrightText, QColor("#ef4444"))
    palette.setColor(QPalette.Link, accent)
    palette.setColor(QPalette.Highlight, accent)
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))

    app.setPalette(palette)
    app.setStyleSheet(DARK_THEME_QSS)

def attach_dark_view(combo: QComboBox):
    """Explicitly attach a styled QListView to any QComboBox to override Windows native popup delegate."""
    view = QListView(combo)
    view.setStyleSheet("""
        QListView {
            background-color: #1e293b;
            color: #f8fafc;
            border: 1px solid #6366f1;
            selection-background-color: #6366f1;
            selection-color: #ffffff;
            outline: 0;
            padding: 4px;
        }
        QListView::item {
            background-color: #1e293b;
            color: #f8fafc;
            padding: 8px 12px;
            min-height: 24px;
        }
        QListView::item:hover, QListView::item:selected {
            background-color: #6366f1;
            color: #ffffff;
        }
    """)
    combo.setView(view)
