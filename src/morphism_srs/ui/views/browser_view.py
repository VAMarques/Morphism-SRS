from __future__ import annotations

import json
import sqlite3

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QUrl, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableView,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from morphism_srs.config import AppConfig
from morphism_srs.controllers.browser_controller import BrowserController
from morphism_srs.controllers.event_bus import EventBus
from morphism_srs.controllers.review_controller import CustomStudyConfig, ReviewController
from morphism_srs.domain.enums import CardState, NoteReviewMode
from morphism_srs.domain.models import NoteModel
from morphism_srs.domain.scheduler_engine import SchedulerEngine
from morphism_srs.storage.media_vault import MediaVault
from morphism_srs.storage.repositories.browser_repo import BrowserNoteRowItem, BrowserRowItem
from morphism_srs.storage.repositories.course_repo import CourseRepository
from morphism_srs.storage.repositories.note_repo import NoteRepository
from morphism_srs.storage.unit_of_work import UnitOfWork
from morphism_srs.theming.delegates import set_widget_props
from morphism_srs.ui.components.search_bar import DebouncedSearchBar
from morphism_srs.ui.dialogs.node_editor_dialog import NodeEditorDialog
from morphism_srs.ui.window_sizing import configure_splitter, wrap_in_scroll_area
from morphism_srs.web_engine.web_profile import WebEngineProfileManager


class BrowserTableModel(QAbstractTableModel):
    """Virtual table model over BrowserRowItem for instantaneous scrolling over thousands of cards."""

    HEADERS = ["Note Title", "Step / Card", "Mode", "State", "R(t)", "Stability", "Due Date", "Lapses", "Tags"]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[BrowserRowItem] = []

    def set_rows(self, rows: list[BrowserRowItem]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def row_at(self, row_idx: int) -> BrowserRowItem | None:
        if 0 <= row_idx < len(self._rows):
            return self._rows[row_idx]
        return None

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(self.HEADERS):
                return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        r = self._rows[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return r.note_title
            if col == 1:
                return f"#{r.step_order + 1}" + (f" ({r.card_title})" if r.card_title else "")
            if col == 2:
                return r.review_mode.upper()
            if col == 3:
                return "SUSPENDED" if r.is_suspended else CardState(r.state).name
            if col == 4:
                if r.state == 0 or r.stability is None or r.last_review_at is None:
                    return "—"
                from morphism_srs.domain.models import CardScheduleModel
                sched = CardScheduleModel(
                    card_id=r.card_id,
                    state=CardState(r.state),
                    stability=r.stability,
                    last_review_at=r.last_review_at,
                )
                return f"{SchedulerEngine.compute_card_retrievability(sched) * 100:.0f}%"
            if col == 5:
                return f"{r.stability:.1f}d" if r.stability is not None else "—"
            if col == 6:
                return r.due_at[:10] if r.due_at else ""
            if col == 8:
                return str(r.lapses)
            if col == 8:
                return str(r.lapses)
            if col == 7:
                return str(r.lapses)
            if col == 8:
                return r.tags_csv
        return None


class NoteBrowserTableModel(QAbstractTableModel):
    """Virtual table model over BrowserNoteRowItem for instantaneous browsing of all notes."""

    HEADERS = ["Note Title", "Mode", "Cards", "Tags", "UUID", "Created"]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[BrowserNoteRowItem] = []

    def set_rows(self, rows: list[BrowserNoteRowItem]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def row_at(self, row_idx: int) -> BrowserNoteRowItem | None:
        if 0 <= row_idx < len(self._rows):
            return self._rows[row_idx]
        return None

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(self.HEADERS):
                return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        r = self._rows[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return r.title
            if col == 1:
                return r.review_mode.upper()
            if col == 2:
                return str(r.card_count)
            if col == 3:
                return r.tags_csv
            if col == 4:
                return r.uuid
            if col == 5:
                return r.created_at
        return None


class BrowserView(QWidget):
    """Dual Mode Mass Browser: Note Browser (Global notes, inject into courses) & Card Browser (All steps/schedules)."""

    FILTER_KIND_ROLE = Qt.ItemDataRole.UserRole
    FILTER_VAL_ROLE = Qt.ItemDataRole.UserRole + 1

    def __init__(
        self,
        conn: sqlite3.Connection,
        config: AppConfig,
        media_vault: MediaVault,
        web_profile: WebEngineProfileManager,
        browser_controller: BrowserController,
        review_controller: ReviewController,
        event_bus: EventBus,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.conn = conn
        self.config = config
        self.media_vault = media_vault
        self.web_profile = web_profile
        self.browser_controller = browser_controller
        self.review_controller = review_controller
        self.event_bus = event_bus

        self.course_repo = CourseRepository(conn)
        self.note_repo = NoteRepository(conn)
        self._preview_ready = False

        self._active_course_filter: int | None = None
        self._active_tag_filter: str | None = None
        self._active_state_filter: int | None = None
        self._active_mode_filter: str | None = None
        self._active_suspended_filter: bool | None = None

        self._build_ui()
        self.event_bus.courses_updated.connect(self.refresh_all)
        self.event_bus.notes_updated.connect(lambda _: self.refresh_all())
        self.refresh_all()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        container = QWidget(self)
        root = QVBoxLayout(container)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        # Top Switcher + Search + Bulk Actions Bar
        top_row = QHBoxLayout()

        self.mode_selector = QComboBox(container)
        self.mode_selector.addItem("🃏 Cards Browser", "cards")
        self.mode_selector.addItem("📝 Notes Browser", "notes")
        self.mode_selector.currentIndexChanged.connect(self._on_browser_mode_changed)
        top_row.addWidget(self.mode_selector)

        self.search_bar = DebouncedSearchBar(
            placeholder='Search (e.g. "homotopy", tag:theorem, mode:serial, is:due)...',
            parent=container,
        )
        self.search_bar.search_triggered.connect(lambda _: self.run_search())
        top_row.addWidget(self.search_bar, 1)

        # Card-Specific Action Buttons Container
        self.cards_actions_widget = QWidget(container)
        ca_layout = QHBoxLayout(self.cards_actions_widget)
        ca_layout.setContentsMargins(0, 0, 0, 0)
        ca_layout.setSpacing(6)

        study_sel_btn = QPushButton("Custom Study Selected", self.cards_actions_widget)
        set_widget_props(study_sel_btn, variant="primary")
        study_sel_btn.clicked.connect(self._on_study_selected)
        ca_layout.addWidget(study_sel_btn)

        tag_btn = QPushButton("+ Tag", self.cards_actions_widget)
        tag_btn.clicked.connect(self._on_bulk_tag)
        ca_layout.addWidget(tag_btn)

        susp_btn = QPushButton("Toggle Suspend", self.cards_actions_widget)
        susp_btn.clicked.connect(self._on_toggle_suspend)
        ca_layout.addWidget(susp_btn)

        reset_btn = QPushButton("Reset Schedule", self.cards_actions_widget)
        reset_btn.clicked.connect(self._on_reset_schedule)
        ca_layout.addWidget(reset_btn)

        top_row.addWidget(self.cards_actions_widget)

        # Note-Specific Action Buttons Container
        self.notes_actions_widget = QWidget(container)
        na_layout = QHBoxLayout(self.notes_actions_widget)
        na_layout.setContentsMargins(0, 0, 0, 0)
        na_layout.setSpacing(6)

        self.inject_btn = QPushButton("📥 Inject into Course...", self.notes_actions_widget)
        set_widget_props(self.inject_btn, variant="primary")
        self.inject_btn.setToolTip("Add selected note(s) into a Course DAG without duplicating data")
        self.inject_btn.clicked.connect(self._on_inject_selected_notes)
        na_layout.addWidget(self.inject_btn)

        new_note_btn = QPushButton("+ New Note", self.notes_actions_widget)
        new_note_btn.clicked.connect(self._on_new_note)
        na_layout.addWidget(new_note_btn)

        edit_note_btn = QPushButton("✏️ Edit Note", self.notes_actions_widget)
        edit_note_btn.clicked.connect(self._on_edit_selected_note)
        na_layout.addWidget(edit_note_btn)

        del_note_btn = QPushButton("🗑️ Delete Permanently", self.notes_actions_widget)
        set_widget_props(del_note_btn, variant="danger")
        del_note_btn.clicked.connect(self._on_delete_selected_notes)
        na_layout.addWidget(del_note_btn)

        self.notes_actions_widget.setVisible(False)
        top_row.addWidget(self.notes_actions_widget)

        root.addLayout(top_row)

        splitter = QSplitter(Qt.Orientation.Horizontal, container)

        # Left Panel: Facet Tree
        self.facet_tree = QTreeWidget(splitter)
        self.facet_tree.setMinimumWidth(180)
        self.facet_tree.setMinimumHeight(260)
        self.facet_tree.setHeaderLabel("Filters")
        self.facet_tree.itemClicked.connect(self._on_facet_clicked)

        # Center Panel: Virtual TableView
        center_widget = QWidget(splitter)
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(4, 0, 4, 0)
        self.count_label = QLabel("0 cards matched", center_widget)
        set_widget_props(self.count_label, role="muted")
        center_layout.addWidget(self.count_label)

        self.card_table_model = BrowserTableModel(center_widget)
        self.note_table_model = NoteBrowserTableModel(center_widget)

        self.table_view = QTableView(center_widget)
        self.table_view.setMinimumWidth(300)
        self.table_view.setMinimumHeight(240)
        self.table_view.setModel(self.card_table_model)
        self.table_view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table_view.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table_view.selectionModel().selectionChanged.connect(self._on_row_selected)
        self.table_view.doubleClicked.connect(self._on_double_click_row)
        center_layout.addWidget(self.table_view, 1)

        # Right Panel: Live Inspector & Jump to Graph
        right_frame = QFrame(splitter)
        set_widget_props(right_frame, role="panel")
        right_layout = QVBoxLayout(right_frame)
        right_layout.setContentsMargins(8, 8, 8, 8)

        insp_top = QHBoxLayout()
        self.insp_lbl = QLabel("Card Inspector", right_frame)
        set_widget_props(self.insp_lbl, role="subtitle")
        insp_top.addWidget(self.insp_lbl)
        insp_top.addStretch(1)

        edit_btn = QPushButton("Edit Note...", right_frame)
        edit_btn.clicked.connect(self._on_edit_selected_note)
        insp_top.addWidget(edit_btn)

        self.jump_btn = QPushButton("Show in Graph", right_frame)
        set_widget_props(self.jump_btn, variant="ghost")
        self.jump_btn.clicked.connect(self._on_jump_to_graph)
        insp_top.addWidget(self.jump_btn)
        right_layout.addLayout(insp_top)

        self.web_view = self.web_profile.create_web_view(right_frame)
        self.web_view.setMinimumHeight(220)
        self.web_view.loadFinished.connect(self._on_preview_loaded)
        self.web_view.setUrl(QUrl("morphism://app/html/preview.html"))
        right_layout.addWidget(self.web_view, 1)

        splitter.addWidget(self.facet_tree)
        splitter.addWidget(center_widget)
        splitter.addWidget(right_frame)
        configure_splitter(splitter, min_sizes=[180, 340, 260], initial_sizes=[200, 440, 300])
        root.addWidget(splitter, 1)

        scroll = wrap_in_scroll_area(container, self, min_width=760, min_height=460)
        outer.addWidget(scroll)

    def _is_notes_mode(self) -> bool:
        return self.mode_selector.currentData() == "notes"

    def _on_browser_mode_changed(self) -> None:
        is_notes = self._is_notes_mode()
        self.cards_actions_widget.setVisible(not is_notes)
        self.notes_actions_widget.setVisible(is_notes)
        self.insp_lbl.setText("Note Inspector" if is_notes else "Card Inspector")
        self.jump_btn.setVisible(not is_notes)

        if is_notes:
            self.table_view.setModel(self.note_table_model)
            self.table_view.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            self.table_view.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        else:
            self.table_view.setModel(self.card_table_model)
            self.table_view.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)

        self.table_view.selectionModel().selectionChanged.connect(self._on_row_selected)
        self._rebuild_facets()
        self.run_search()

    def refresh_all(self) -> None:
        self._rebuild_facets()
        self.run_search()

    def _rebuild_facets(self) -> None:
        self.facet_tree.clear()

        all_item = QTreeWidgetItem(["All Items"])
        all_item.setData(0, self.FILTER_KIND_ROLE, "all")
        self.facet_tree.addTopLevelItem(all_item)

        if not self._is_notes_mode():
            states_root = QTreeWidgetItem(["Card State"])
            for label, val in [
                ("New", 0),
                ("Learning", 1),
                ("Review", 2),
                ("Relearning", 3),
                ("Suspended", "suspended"),
            ]:
                it = QTreeWidgetItem([label])
                it.setData(0, self.FILTER_KIND_ROLE, "state")
                it.setData(0, self.FILTER_VAL_ROLE, val)
                states_root.addChild(it)
            self.facet_tree.addTopLevelItem(states_root)
            states_root.setExpanded(True)

        modes_root = QTreeWidgetItem(["Review Mode"])
        for label, mval in [
            ("Standard (Rectangle)", "standard"),
            ("Serial (Diamond)", "serial"),
            ("Cloze (Ellipse)", "cloze"),
        ]:
            it = QTreeWidgetItem([label])
            it.setData(0, self.FILTER_KIND_ROLE, "mode")
            it.setData(0, self.FILTER_VAL_ROLE, mval)
            modes_root.addChild(it)
        self.facet_tree.addTopLevelItem(modes_root)
        modes_root.setExpanded(True)

        courses_root = QTreeWidgetItem(["Courses (Reference)"])
        for c in self.course_repo.list_all():
            it = QTreeWidgetItem([c.name])
            it.setData(0, self.FILTER_KIND_ROLE, "course")
            it.setData(0, self.FILTER_VAL_ROLE, c.id)
            courses_root.addChild(it)

        na_item = QTreeWidgetItem(["N/A (Unassigned)"])
        na_item.setData(0, self.FILTER_KIND_ROLE, "course")
        na_item.setData(0, self.FILTER_VAL_ROLE, -1)
        courses_root.addChild(na_item)

        self.facet_tree.addTopLevelItem(courses_root)
        courses_root.setExpanded(True)

        tags_root = QTreeWidgetItem(["Used Tags"])
        used_rows = self.conn.execute(
            """
            SELECT DISTINCT t.name
            FROM tags t
            JOIN note_tags nt ON nt.tag_id = t.id
            ORDER BY t.name ASC LIMIT 200;
            """
        ).fetchall()
        for r in used_rows:
            tname = str(r["name"])
            it = QTreeWidgetItem([f"#{tname}"])
            it.setData(0, self.FILTER_KIND_ROLE, "tag")
            it.setData(0, self.FILTER_VAL_ROLE, tname)
            tags_root.addChild(it)
        self.facet_tree.addTopLevelItem(tags_root)
        tags_root.setExpanded(True)

    def _on_facet_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        kind = item.data(0, self.FILTER_KIND_ROLE)
        val = item.data(0, self.FILTER_VAL_ROLE)

        self._active_course_filter = None
        self._active_tag_filter = None
        self._active_state_filter = None
        self._active_mode_filter = None
        self._active_suspended_filter = None

        if kind == "course" and val is not None:
            self._active_course_filter = int(val)
        elif kind == "tag" and val is not None:
            self._active_tag_filter = str(val)
        elif kind == "state":
            if val == "suspended":
                self._active_suspended_filter = True
            elif val is not None:
                self._active_state_filter = int(val)
        elif kind == "mode" and val is not None:
            self._active_mode_filter = str(val)

        self.run_search()

    def run_search(self) -> None:
        q = self.search_bar.text()
        if self._is_notes_mode():
            note_rows = self.browser_controller.search_notes(
                query_text=q,
                course_id=self._active_course_filter,
                tag_filter=self._active_tag_filter,
                review_mode_filter=self._active_mode_filter,
            )
            self.note_table_model.set_rows(note_rows)
            self.count_label.setText(f"{len(note_rows)} note(s) matched")
            if note_rows:
                self.table_view.selectRow(0)
        else:
            card_rows = self.browser_controller.search(
                query_text=q,
                course_id=self._active_course_filter,
                tag_filter=self._active_tag_filter,
                state_filter=self._active_state_filter,
                review_mode_filter=self._active_mode_filter,
                suspended_filter=self._active_suspended_filter,
            )
            self.card_table_model.set_rows(card_rows)
            self.count_label.setText(f"{len(card_rows)} card(s) matched")
            if card_rows:
                self.table_view.selectRow(0)

    def _selected_card_rows(self) -> list[BrowserRowItem]:
        indexes = self.table_view.selectionModel().selectedRows()
        items: list[BrowserRowItem] = []
        for idx in indexes:
            r = self.card_table_model.row_at(idx.row())
            if r is not None:
                items.append(r)
        return items

    def _selected_note_rows(self) -> list[BrowserNoteRowItem]:
        indexes = self.table_view.selectionModel().selectedRows()
        items: list[BrowserNoteRowItem] = []
        for idx in indexes:
            r = self.note_table_model.row_at(idx.row())
            if r is not None:
                items.append(r)
        return items

    def _on_preview_loaded(self, ok: bool) -> None:
        self._preview_ready = ok
        if ok:
            self._on_row_selected()

    def _on_row_selected(self, *_args) -> None:
        if not self._preview_ready:
            return
        if self._is_notes_mode():
            sel_notes = self._selected_note_rows()
            if not sel_notes:
                return
            n_row = sel_notes[0]
            note = self.note_repo.get_by_id(n_row.note_id, include_children=True)
            if not note:
                return
            cards_payload = [
                {
                    "title": c.title or f"Step {c.step_order + 1}",
                    "front_html": c.front_html,
                    "back_html": c.back_html,
                    "hint_html": c.hint_html,
                }
                for c in note.cards
            ]
            payload = {
                "title": note.title,
                "review_mode": note.review_mode.value,
                "tags": note.tags,
                "premise_html": note.premise_html,
                "cards": cards_payload,
            }
            self.web_view.page().runJavaScript(
                f"if (window.MorphismPreview) {{ window.MorphismPreview.renderPreview({json.dumps(payload)}); }}"
            )
        else:
            sel_cards = self._selected_card_rows()
            if not sel_cards:
                return
            r = sel_cards[0]
            payload = {
                "title": r.note_title,
                "review_mode": r.review_mode,
                "tags": [t.strip() for t in r.tags_csv.split(",") if t.strip()],
                "premise_html": "",
                "cards": [
                    {
                        "title": r.card_title or f"Step {r.step_order + 1}",
                        "front_html": r.front_html,
                        "back_html": r.back_html,
                        "hint_html": "",
                    }
                ],
            }
            self.web_view.page().runJavaScript(
                f"if (window.MorphismPreview) {{ window.MorphismPreview.renderPreview({json.dumps(payload)}); }}"
            )

    def _on_double_click_row(self, index: QModelIndex) -> None:
        self._on_edit_selected_note()

    def _on_inject_selected_notes(self) -> None:
        sel = self._selected_note_rows()
        if not sel:
            QMessageBox.information(self, "No Selection", "Please select one or more notes to inject into a course.")
            return
        courses = self.course_repo.list_all()
        if not courses:
            QMessageBox.information(self, "No Courses", "Please create a course before injecting notes.")
            return
        c_names = [c.name for c in courses]
        chosen_name, ok = QInputDialog.getItem(
            self,
            "Inject Notes into Course",
            f"Select destination Course for {len(sel)} note(s):",
            c_names,
            0,
            False,
        )
        if not ok or not chosen_name:
            return
        target = next((c for c in courses if c.name == chosen_name), None)
        if not target or target.id is None:
            return

        with UnitOfWork(self.conn):
            for n in sel:
                self.note_repo.inject_into_course(target.id, n.note_id, 0.0, 0.0)

        self.event_bus.notes_updated.emit(target.id)
        self.event_bus.courses_updated.emit()
        QMessageBox.information(
            self,
            "Notes Injected",
            f"Successfully injected {len(sel)} note(s) into course '{target.name}'.",
        )

    def _on_new_note(self) -> None:
        courses = self.course_repo.list_all()
        cid = courses[0].id if courses else None
        dlg = NodeEditorDialog(
            conn=self.conn,
            config=self.config,
            media_vault=self.media_vault,
            web_profile=self.web_profile,
            course_id=cid,
            parent=self,
        )
        if dlg.exec():
            self.refresh_all()

    def _on_delete_selected_notes(self) -> None:
        sel = self._selected_note_rows()
        if not sel:
            return
        reply = QMessageBox.question(
            self,
            "Delete Permanently",
            f"Permanently delete {len(sel)} note(s) and all their cards from the entire database?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            with UnitOfWork(self.conn):
                for n in sel:
                    self.note_repo.delete(n.note_id)
            self.refresh_all()
            self.event_bus.courses_updated.emit()

    def _on_study_selected(self) -> None:
        sel = self._selected_card_rows()
        if not sel:
            return
        note_ids = sorted({r.note_id for r in sel})
        cfg = CustomStudyConfig(note_ids=note_ids, only_due_or_new=False, sort_criterion="topological_due")
        if self.review_controller.start_custom_study(cfg) > 0:
            self.event_bus.navigate_to_tab.emit("review")

    def _on_bulk_tag(self) -> None:
        if self._is_notes_mode():
            sel_n = self._selected_note_rows()
            if not sel_n:
                return
            tag, ok = QInputDialog.getText(self, "Add Tag to Selected Notes", "Tag name:")
            if ok and tag.strip():
                self.browser_controller.add_tag_to_notes([n.note_id for n in sel_n], tag.strip())
                self.refresh_all()
        else:
            sel_c = self._selected_card_rows()
            if not sel_c:
                return
            tag, ok = QInputDialog.getText(self, "Add Tag to Selected Notes", "Tag name:")
            if ok and tag.strip():
                note_ids = sorted({r.note_id for r in sel_c})
                self.browser_controller.add_tag_to_notes(note_ids, tag.strip())
                self.refresh_all()

    def _on_toggle_suspend(self) -> None:
        sel = self._selected_card_rows()
        if not sel:
            return
        target_susp = not sel[0].is_suspended
        self.browser_controller.suspend_cards([r.card_id for r in sel], target_susp)
        self.run_search()

    def _on_reset_schedule(self) -> None:
        sel = self._selected_card_rows()
        if not sel:
            return
        self.browser_controller.reset_cards([r.card_id for r in sel])
        self.run_search()

    def _on_edit_selected_note(self) -> None:
        nid = None
        cid = None
        if self._is_notes_mode():
            sel_n = self._selected_note_rows()
            if sel_n:
                nid = sel_n[0].note_id
        else:
            sel_c = self._selected_card_rows()
            if sel_c:
                nid = sel_c[0].note_id
                cid = sel_c[0].course_id or None

        if nid is None:
            return
        note = self.note_repo.get_by_id(nid, include_children=True)
        if note is None:
            return
        dlg = NodeEditorDialog(
            conn=self.conn,
            config=self.config,
            media_vault=self.media_vault,
            web_profile=self.web_profile,
            course_id=cid or note.course_id,
            note=note,
            parent=self,
        )
        if dlg.exec():
            self.refresh_all()

    def _on_jump_to_graph(self) -> None:
        if self._is_notes_mode():
            sel_n = self._selected_note_rows()
            if not sel_n:
                return
            nid = sel_n[0].note_id
            note = self.note_repo.get_by_id(nid, include_children=False)
            if note and note.course_id:
                self.event_bus.open_node_in_explorer.emit(note.course_id, note.id)
                self.event_bus.navigate_to_tab.emit("explorer")
        else:
            sel_c = self._selected_card_rows()
            if not sel_c:
                return
            r = sel_c[0]
            if r.course_id:
                self.event_bus.open_node_in_explorer.emit(r.course_id, r.note_id)
                self.event_bus.navigate_to_tab.emit("explorer")
