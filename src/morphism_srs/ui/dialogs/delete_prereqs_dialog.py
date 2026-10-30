from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from morphism_srs.theming.delegates import set_widget_props
from morphism_srs.ui.window_sizing import apply_relative_geometry


class DeleteNoteDialog(QDialog):
    """Confirmation dialog when removing DAG nodes, offering soft-delete (unlink) vs hard-delete."""

    def __init__(self, note_count: int = 1, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Remove / Delete Note(s)")
        apply_relative_geometry(self, width_ratio=0.42, height_ratio=0.34, min_width=460, min_height=260)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        lbl = QLabel(
            f"What would you like to do with the {note_count} selected note(s)?",
            self,
        )
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        self.unlink_rb = QRadioButton("🔗 Unlink from Course (Soft-Delete)", self)
        self.unlink_rb.setToolTip(
            "Removes node(s) from this course DAG, but keeps notes, cards, and review schedules intact in the database."
        )
        self.unlink_rb.setChecked(True)
        layout.addWidget(self.unlink_rb)

        self.hard_del_rb = QRadioButton("🗑️ Delete Permanently from Database (Hard-Delete)", self)
        self.hard_del_rb.setToolTip(
            "Completely deletes node(s), all their cards, and review history from the database."
        )
        layout.addWidget(self.hard_del_rb)

        self.bridge_cb = QCheckBox(
            "Bridge prerequisite edges (connect parent prerequisites directly to child dependents)",
            self,
        )
        self.bridge_cb.setChecked(True)
        layout.addWidget(self.bridge_cb)
        layout.addStretch(1)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel_btn = QPushButton("Cancel", self)
        cancel_btn.clicked.connect(self.reject)
        confirm_btn = QPushButton("Confirm", self)
        set_widget_props(confirm_btn, variant="primary")
        confirm_btn.clicked.connect(self.accept)
        row.addWidget(cancel_btn)
        row.addWidget(confirm_btn)
        layout.addLayout(row)

    @property
    def is_unlink_only(self) -> bool:
        return self.unlink_rb.isChecked()

    @property
    def bridge_edges(self) -> bool:
        return self.bridge_cb.isChecked()


class DeletePrereqsDialog(QDialog):
    """Dialog to selectively remove prerequisite / dependency edges attached to a Note."""

    def __init__(
        self,
        note_title: str,
        edge_items: list[tuple[int, int, str]],
        parent: QWidget | None = None,
    ) -> None:
        """
        edge_items: list of (source_note_id, target_note_id, human_readable_label)
        """
        super().__init__(parent)
        self.setWindowTitle(f"Remove Prerequisite Links — {note_title}")
        apply_relative_geometry(self, width_ratio=0.42, height_ratio=0.45, min_width=460, min_height=320)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        lbl = QLabel(f"Select prerequisite links to remove from <b>{note_title}</b>:", self)
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        self.list_widget = QListWidget(self)
        self.list_widget.setMinimumHeight(160)
        for src_id, dst_id, desc in edge_items:
            it = QListWidgetItem(desc, self.list_widget)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Unchecked)
            it.setData(Qt.ItemDataRole.UserRole, (src_id, dst_id))
        layout.addWidget(self.list_widget, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel_btn = QPushButton("Cancel", self)
        cancel_btn.clicked.connect(self.reject)
        rm_btn = QPushButton("Remove Selected Links", self)
        set_widget_props(rm_btn, variant="danger")
        rm_btn.clicked.connect(self.accept)
        row.addWidget(cancel_btn)
        row.addWidget(rm_btn)
        layout.addLayout(row)

    def selected_edges(self) -> list[tuple[int, int]]:
        out: list[tuple[int, int]] = []
        for idx in range(self.list_widget.count()):
            it = self.list_widget.item(idx)
            if it.checkState() == Qt.CheckState.Checked:
                pair = it.data(Qt.ItemDataRole.UserRole)
                if pair:
                    out.append((int(pair[0]), int(pair[1])))
        return out
