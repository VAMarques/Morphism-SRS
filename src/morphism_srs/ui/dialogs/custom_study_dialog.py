from __future__ import annotations

import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from morphism_srs.controllers.review_controller import CustomStudyConfig
from morphism_srs.storage.repositories.course_repo import CourseRepository
from morphism_srs.storage.repositories.note_repo import NoteRepository
from morphism_srs.theming.delegates import set_widget_props
from morphism_srs.ui.components.tag_chips import TagChipsWidget
from morphism_srs.ui.window_sizing import apply_relative_geometry, wrap_in_scroll_area


class CustomStudyDialog(QDialog):
    """Dialog to configure Custom Study sessions (by bottleneck R_min, joint retrieval, tags, etc.)."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        initial_course_ids: list[int] | None = None,
        initial_note_ids: list[int] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Custom Study Session")
        apply_relative_geometry(self, width_ratio=0.54, height_ratio=0.70, min_width=540, min_height=460)

        self.conn = conn
        self.course_repo = CourseRepository(conn)
        self.note_repo = NoteRepository(conn)
        self._initial_note_ids = list(initial_note_ids or [])

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        container = QWidget(self)
        root = QVBoxLayout(container)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QLabel("Configure Custom Study Queue", container)
        set_widget_props(title, role="title")
        root.addWidget(title)

        form = QFormLayout()
        form.setSpacing(10)

        self.courses_list = QListWidget(container)
        self.courses_list.setMinimumHeight(95)
        initial_cset = set(initial_course_ids or [])
        for c in self.course_repo.list_all():
            item = QListWidgetItem(c.name, self.courses_list)
            item.setData(Qt.ItemDataRole.UserRole, c.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            checked = (c.id in initial_cset) or (not initial_cset and not self._initial_note_ids)
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        form.addRow("Courses:", self.courses_list)

        all_tags = [t.name for t in self.note_repo.list_all_tags()]
        self.tag_widget = TagChipsWidget(all_tags, container)
        form.addRow("Filter by Tags:", self.tag_widget)

        self.sort_combo = QComboBox(container)
        self.sort_combo.addItem("Topological DAG Order + Due Date", "topological_due")
        self.sort_combo.addItem("Bottleneck Retrievability (Lowest R_min first)", "bottleneck_r_min")
        self.sort_combo.addItem("Joint Retrieval Probability (Lowest P(∩ A_i) first)", "joint_retrieval")
        self.sort_combo.addItem("Lowest Stability (S)", "lowest_stability")
        self.sort_combo.addItem("Most Lapses (Leech Cards)", "most_lapses")
        form.addRow("Order By:", self.sort_combo)

        self.only_due_cb = QCheckBox("Only include Due or New cards", container)
        self.only_due_cb.setChecked(False)
        form.addRow("", self.only_due_cb)

        self.prereqs_cb = QCheckBox("Include recursive DAG prerequisite ancestors", container)
        self.prereqs_cb.setChecked(bool(self._initial_note_ids))
        form.addRow("", self.prereqs_cb)

        self.ahead_spin = QSpinBox(container)
        self.ahead_spin.setRange(0, 365)
        self.ahead_spin.setValue(0)
        self.ahead_spin.setSuffix(" days ahead")
        form.addRow("Review Ahead:", self.ahead_spin)

        self.failed_spin = QSpinBox(container)
        self.failed_spin.setRange(0, 365)
        self.failed_spin.setValue(0)
        self.failed_spin.setSpecialValueText("Disabled")
        self.failed_spin.setSuffix(" days")
        form.addRow("Failed Within:", self.failed_spin)

        self.max_cards_spin = QSpinBox(container)
        self.max_cards_spin.setRange(1, 2000)
        self.max_cards_spin.setValue(100)
        form.addRow("Max Cards:", self.max_cards_spin)

        self.cram_cb = QCheckBox("Cram / Sandbox Mode (do not alter FSRS schedules)", container)
        self.cram_cb.setChecked(False)
        form.addRow("", self.cram_cb)

        root.addLayout(form)
        root.addStretch(1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = QPushButton("Cancel", container)
        cancel_btn.clicked.connect(self.reject)
        start_btn = QPushButton("Start Custom Study", container)
        set_widget_props(start_btn, variant="primary")
        start_btn.clicked.connect(self.accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(start_btn)
        root.addLayout(btn_row)

        scroll = wrap_in_scroll_area(container, self, min_width=500, min_height=430)
        outer.addWidget(scroll)

    def build_config(self) -> CustomStudyConfig:
        selected_courses: list[int] = []
        for idx in range(self.courses_list.count()):
            item = self.courses_list.item(idx)
            if item.checkState() == Qt.CheckState.Checked:
                cid = item.data(Qt.ItemDataRole.UserRole)
                if cid is not None:
                    selected_courses.append(int(cid))

        failed_days = self.failed_spin.value()
        return CustomStudyConfig(
            course_ids=selected_courses,
            note_ids=self._initial_note_ids,
            tags=self.tag_widget.tags(),
            include_prerequisite_ancestors=self.prereqs_cb.isChecked(),
            only_due_or_new=self.only_due_cb.isChecked(),
            ahead_days=self.ahead_spin.value(),
            failed_within_days=failed_days if failed_days > 0 else None,
            sort_criterion=str(self.sort_combo.currentData() or "topological_due"),
            max_cards=self.max_cards_spin.value(),
            cram_sandbox=self.cram_cb.isChecked(),
        )
