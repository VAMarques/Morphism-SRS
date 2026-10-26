from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QWidget

from morphism_srs.theming.delegates import set_widget_props


class DebouncedSearchBar(QWidget):
    """Debounced search bar with quick clear button."""

    search_triggered = Signal(str)

    def __init__(self, placeholder: str = "Search...", debounce_ms: int = 180, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(debounce_ms)
        self._timer.timeout.connect(self._emit_search)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.line_edit = QLineEdit(self)
        self.line_edit.setPlaceholderText(placeholder)
        self.line_edit.textChanged.connect(lambda _: self._timer.start())
        self.line_edit.returnPressed.connect(self._emit_search)

        self.clear_btn = QPushButton("Clear", self)
        set_widget_props(self.clear_btn, variant="ghost")
        self.clear_btn.clicked.connect(self.clear)

        layout.addWidget(self.line_edit, 1)
        layout.addWidget(self.clear_btn)

    def text(self) -> str:
        return self.line_edit.text().strip()

    def set_text(self, value: str) -> None:
        self.line_edit.setText(value)
        self._emit_search()

    def clear(self) -> None:
        self.line_edit.clear()
        self._emit_search()

    def _emit_search(self) -> None:
        self._timer.stop()
        self.search_triggered.emit(self.line_edit.text().strip())
