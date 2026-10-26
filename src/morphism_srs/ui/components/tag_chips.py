from __future__ import annotations

from PySide6.QtCore import QStringListModel, Qt, Signal
from PySide6.QtWidgets import (
    QCompleter,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from morphism_srs.theming.delegates import set_widget_props
from morphism_srs.ui.components.flow_layout import FlowLayout


class TagChipsWidget(QWidget):
    """Widget with QCompleter over the 2,000 default tags and interactive removable tag chips."""

    tags_changed = Signal(list)

    def __init__(self, all_tag_names: list[str] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tags: list[str] = []
        self._all_tag_names = sorted(set(all_tag_names or []))

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        input_row = QHBoxLayout()
        input_row.setContentsMargins(0, 0, 0, 0)
        self.line_edit = QLineEdit(self)
        self.line_edit.setPlaceholderText("Add tag (e.g. algebraic_topology, theorem, sylow_theorems)...")

        self.completer = QCompleter(self._all_tag_names, self)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.line_edit.setCompleter(self.completer)
        self.line_edit.returnPressed.connect(self._on_add_from_input)

        self.add_btn = QPushButton("+ Tag", self)
        self.add_btn.clicked.connect(self._on_add_from_input)

        input_row.addWidget(self.line_edit, 1)
        input_row.addWidget(self.add_btn)
        root.addLayout(input_row)

        self.chips_container = QWidget(self)
        self.flow_layout = FlowLayout(self.chips_container, margin=0, spacing=6)
        root.addWidget(self.chips_container)

    def set_available_tags(self, tag_names: list[str]) -> None:
        self._all_tag_names = sorted(set(tag_names))
        self.completer.setModel(QStringListModel(self._all_tag_names, self.completer))

    def tags(self) -> list[str]:
        return list(self._tags)

    def set_tags(self, tags: list[str]) -> None:
        cleaned: list[str] = []
        for t in tags:
            c = t.strip().lower().replace(" ", "_")
            if c and c not in cleaned:
                cleaned.append(c)
        self._tags = cleaned
        self._rebuild_chips()

    def _on_add_from_input(self) -> None:
        raw = self.line_edit.text().strip().lower().replace(" ", "_")
        if not raw:
            return
        self.line_edit.clear()
        if raw not in self._tags:
            self._tags.append(raw)
            self._rebuild_chips()
            self.tags_changed.emit(list(self._tags))

    def remove_tag(self, tag: str) -> None:
        if tag in self._tags:
            self._tags.remove(tag)
            self._rebuild_chips()
            self.tags_changed.emit(list(self._tags))

    def _rebuild_chips(self) -> None:
        while self.flow_layout.count():
            item = self.flow_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        for t in self._tags:
            btn = QPushButton(f"#{t}  ✕", self.chips_container)
            set_widget_props(btn, variant="ghost")
            btn.clicked.connect(lambda _=False, tag_val=t: self.remove_tag(tag_val))
            self.flow_layout.addWidget(btn)
