from __future__ import annotations

from pathlib import Path
import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from morphism_srs.config import get_project_root
from morphism_srs.controllers.event_bus import EventBus
from morphism_srs.controllers.review_controller import ReviewController
from morphism_srs.domain.models import CourseFolderModel, CourseModel
from morphism_srs.services.dsl_compiler.compiler import DSLCompiler
from morphism_srs.services.import_export.json_service import JsonImportExportService
from morphism_srs.services.import_export.mpkg_service import MpkgService
from morphism_srs.storage.media_vault import MediaVault
from morphism_srs.storage.repositories.course_repo import CourseRepository
from morphism_srs.storage.repositories.folder_repo import FolderRepository
from morphism_srs.storage.repositories.note_repo import NoteRepository
from morphism_srs.storage.unit_of_work import UnitOfWork
from morphism_srs.theming.delegates import set_widget_props
from morphism_srs.ui.dialogs.custom_study_dialog import CustomStudyDialog
from morphism_srs.ui.window_sizing import apply_relative_geometry, wrap_in_scroll_area


class CourseEditDialog(QDialog):
    """Dialog to create or edit a Course (name, folder, color_hex, desired_retention)."""

    def __init__(
        self,
        folders: list[CourseFolderModel],
        course: CourseModel | None = None,
        default_folder_id: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Course" if course else "New Course")
        apply_relative_geometry(self, width_ratio=0.40, height_ratio=0.38, min_width=420, min_height=280)

        self.course = course or CourseModel(folder_id=default_folder_id)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        form = QFormLayout()

        self.name_edit = QLineEdit(self.course.name, self)
        form.addRow("Course Name:", self.name_edit)

        from PySide6.QtWidgets import QComboBox
        self.folder_combo = QComboBox(self)
        self.folder_combo.addItem("(Root Level)", None)
        for f in folders:
            self.folder_combo.addItem(f.name, f.id)
        idx = self.folder_combo.findData(self.course.folder_id)
        if idx >= 0:
            self.folder_combo.setCurrentIndex(idx)
        form.addRow("Folder:", self.folder_combo)

        self.color_edit = QLineEdit(self.course.color_hex or "#89b4fa", self)
        form.addRow("Accent Color (Hex):", self.color_edit)

        self.ret_spin = QDoubleSpinBox(self)
        self.ret_spin.setRange(0.70, 0.99)
        self.ret_spin.setSingleStep(0.01)
        self.ret_spin.setValue(self.course.desired_retention)
        form.addRow("Desired Retention:", self.ret_spin)

        root.addLayout(form)
        root.addStretch(1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel_btn = QPushButton("Cancel", self)
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Save", self)
        set_widget_props(save_btn, variant="primary")
        save_btn.clicked.connect(self._on_save)
        btns.addWidget(cancel_btn)
        btns.addWidget(save_btn)
        root.addLayout(btns)

    def _on_save(self) -> None:
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "Missing Name", "Course name cannot be empty.")
            return
        self.course.name = self.name_edit.text().strip()
        self.course.folder_id = self.folder_combo.currentData()
        self.course.color_hex = self.color_edit.text().strip() or "#89b4fa"
        self.course.desired_retention = self.ret_spin.value()
        self.accept()


class CoursesView(QWidget):
    """Hierarchical Folder & Course Tree View with Graph Explorer launcher, Import/Export (.mdsl, .mpkg, .json), and Custom Study."""

    ITEM_TYPE_ROLE = Qt.ItemDataRole.UserRole
    ITEM_ID_ROLE = Qt.ItemDataRole.UserRole + 1

    def __init__(
        self,
        conn: sqlite3.Connection,
        media_vault: MediaVault,
        review_controller: ReviewController,
        event_bus: EventBus,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.conn = conn
        self.media_vault = media_vault
        self.review_controller = review_controller
        self.event_bus = event_bus

        self.folder_repo = FolderRepository(conn)
        self.course_repo = CourseRepository(conn)
        self.note_repo = NoteRepository(conn)
        self.mpkg_service = MpkgService(conn, media_vault)
        self.json_service = JsonImportExportService(conn)
        self.dsl_compiler = DSLCompiler(conn, media_vault)

        self._build_ui()
        self.event_bus.courses_updated.connect(self.refresh_tree)
        self.event_bus.review_state_changed.connect(self.refresh_tree)
        self.event_bus.notes_updated.connect(lambda _: self.refresh_tree())
        self.refresh_tree()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        container = QWidget(self)
        root = QVBoxLayout(container)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        header_row = QHBoxLayout()
        title = QLabel("Courses & Knowledge Folders", container)
        set_widget_props(title, role="title")
        header_row.addWidget(title)
        header_row.addStretch(1)

        open_dag_btn = QPushButton("🕸️ Open in Graph Explorer", container)
        set_widget_props(open_dag_btn, variant="primary")
        open_dag_btn.clicked.connect(self._on_open_selected_in_explorer)
        header_row.addWidget(open_dag_btn)

        new_folder_btn = QPushButton("+ New Folder", container)
        new_folder_btn.clicked.connect(self._on_new_folder)
        header_row.addWidget(new_folder_btn)

        new_course_btn = QPushButton("+ New Course", container)
        new_course_btn.clicked.connect(self._on_new_course)
        header_row.addWidget(new_course_btn)

        import_btn = QPushButton("📥 Import (to_import/ .mdsl / .json / .mpkg)...", container)
        import_btn.clicked.connect(self._on_import_deck)
        header_row.addWidget(import_btn)

        export_btn = QPushButton("📤 Export Course...", container)
        export_btn.clicked.connect(self._on_export_button_clicked)
        header_row.addWidget(export_btn)

        custom_study_btn = QPushButton("Custom Study...", container)
        set_widget_props(custom_study_btn, variant="ghost")
        custom_study_btn.clicked.connect(self._on_custom_study_selected)
        header_row.addWidget(custom_study_btn)

        auto_study_btn = QPushButton("Auto-Study Due", container)
        set_widget_props(auto_study_btn, variant="ghost")
        auto_study_btn.setToolTip("Secondary mode: queue due cards automatically (Primary mode is clicking nodes in Graph Explorer)")
        auto_study_btn.clicked.connect(self._on_auto_study_selected)
        header_row.addWidget(auto_study_btn)

        root.addLayout(header_row)

        self.tree = QTreeWidget(container)
        self.tree.setMinimumHeight(260)
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["Folder / Course", "Notes", "Cards", "Due Now", "New"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 5):
            self.tree.header().setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        root.addWidget(self.tree, 1)

        scroll = wrap_in_scroll_area(container, self, min_width=640, min_height=420)
        outer.addWidget(scroll)

    def _on_open_selected_in_explorer(self) -> None:
        kind, item_id = self._selected_type_and_id()
        if kind == "course" and item_id is not None:
            self.event_bus.course_selected.emit(int(item_id))
        self.event_bus.navigate_to_tab.emit("explorer")

    def refresh_tree(self) -> None:
        self.tree.clear()
        folders = self.folder_repo.list_all()
        courses = self.course_repo.list_all()
        counts = self.course_repo.get_course_counts()

        folder_items: dict[int, QTreeWidgetItem] = {}
        for f in folders:
            if f.id is None:
                continue
            item = QTreeWidgetItem([f"📁 {f.name}", "", "", "", ""])
            item.setData(0, self.ITEM_TYPE_ROLE, "folder")
            item.setData(0, self.ITEM_ID_ROLE, f.id)
            folder_items[f.id] = item

        for f in folders:
            if f.id is None:
                continue
            item = folder_items[f.id]
            if f.parent_id and f.parent_id in folder_items:
                folder_items[f.parent_id].addChild(item)
            else:
                self.tree.addTopLevelItem(item)
            item.setExpanded(f.is_expanded)

        for c in courses:
            if c.id is None:
                continue
            st = counts.get(c.id, {"notes": 0, "cards": 0, "due": 0, "new": 0})
            c_item = QTreeWidgetItem(
                [
                    f"📘 {c.name}",
                    str(st["notes"]),
                    str(st["cards"]),
                    str(st["due"]),
                    str(st["new"]),
                ]
            )
            c_item.setData(0, self.ITEM_TYPE_ROLE, "course")
            c_item.setData(0, self.ITEM_ID_ROLE, c.id)
            if c.folder_id and c.folder_id in folder_items:
                folder_items[c.folder_id].addChild(c_item)
            else:
                self.tree.addTopLevelItem(c_item)

    def _selected_type_and_id(self) -> tuple[str | None, int | None]:
        items = self.tree.selectedItems()
        if not items:
            return None, None
        it = items[0]
        return it.data(0, self.ITEM_TYPE_ROLE), it.data(0, self.ITEM_ID_ROLE)

    def _on_item_double_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        kind = item.data(0, self.ITEM_TYPE_ROLE)
        item_id = item.data(0, self.ITEM_ID_ROLE)
        if kind == "course" and item_id is not None:
            self.event_bus.course_selected.emit(int(item_id))
            self.event_bus.navigate_to_tab.emit("explorer")

    def _on_new_folder(self) -> None:
        kind, item_id = self._selected_type_and_id()
        parent_id = int(item_id) if kind == "folder" and item_id is not None else None
        name, ok = QInputDialog.getText(self, "New Folder", "Folder Name:")
        if not ok or not name.strip():
            return
        with UnitOfWork(self.conn):
            self.folder_repo.create(CourseFolderModel(name=name.strip(), parent_id=parent_id))
        self.refresh_tree()

    def _on_new_course(self) -> None:
        kind, item_id = self._selected_type_and_id()
        default_fid = int(item_id) if kind == "folder" and item_id is not None else None
        dlg = CourseEditDialog(self.folder_repo.list_all(), default_folder_id=default_fid, parent=self)
        if dlg.exec():
            with UnitOfWork(self.conn):
                self.course_repo.create(dlg.course)
            self.event_bus.courses_updated.emit()

    def _on_auto_study_selected(self) -> None:
        kind, item_id = self._selected_type_and_id()
        if kind == "course" and item_id is not None:
            cnt = self.review_controller.start_auto_study(course_ids=[int(item_id)])
        elif kind == "folder" and item_id is not None:
            cnt = self.review_controller.start_auto_study(folder_id=int(item_id))
        else:
            cnt = self.review_controller.start_auto_study()
        if cnt == 0:
            QMessageBox.information(self, "No Cards Due", "No Due or New cards found in the selected scope.")
            return
        self.event_bus.navigate_to_tab.emit("review")

    def _on_custom_study_selected(self) -> None:
        kind, item_id = self._selected_type_and_id()
        init_courses = [int(item_id)] if kind == "course" and item_id is not None else None
        dlg = CustomStudyDialog(self.conn, initial_course_ids=init_courses, parent=self)
        if dlg.exec():
            cnt = self.review_controller.start_custom_study(dlg.build_config())
            if cnt == 0:
                QMessageBox.information(self, "Empty Queue", "No cards matched your Custom Study filters.")
                return
            self.event_bus.navigate_to_tab.emit("review")

    def _on_import_deck(self) -> None:
        to_import_dir = get_project_root() / "to_import"
        start_dir = str(to_import_dir) if to_import_dir.exists() else ""
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Import Morphism Deck (.mdsl / .json / .mpkg)",
            start_dir,
            "Morphism Decks (*.mdsl *.json *.mpkg)",
        )
        if not path_str:
            return
        p = Path(path_str)
        kind, item_id = self._selected_type_and_id()
        selected_course_id = int(item_id) if kind == "course" and item_id is not None else None
        try:
            if p.suffix.lower() == ".mpkg":
                cid = self.mpkg_service.import_mpkg(p, include_scheduling=True)
            elif p.suffix.lower() == ".json":
                cid = self.json_service.import_course_file(p, include_scheduling=True)
            else:
                res = self.dsl_compiler.compile_and_commit(
                    p.read_text(encoding="utf-8"),
                    target_course_id=selected_course_id,
                    auto_layout=True,
                    source_dir=p.parent,
                    media_vault=self.media_vault,
                )
                if res.has_errors:
                    QMessageBox.critical(self, "DSL Import Error", res.diagnostics[0].message)
                    return
                cid = res.course_id or 0
            self.event_bus.courses_updated.emit()
            if cid:
                self.event_bus.course_selected.emit(cid)
            QMessageBox.information(self, "Import Complete", f"Successfully imported '{p.name}'.")
        except Exception as exc:
            QMessageBox.critical(self, "Import Failed", str(exc))

    def _on_export_button_clicked(self) -> None:
        kind, item_id = self._selected_type_and_id()
        selected_cid = int(item_id) if kind == "course" and item_id is not None else None
        all_courses = self.course_repo.list_all()
        if not all_courses:
            QMessageBox.information(self, "No Courses", "There are no courses in the database to export.")
            return

        if selected_cid is None:
            c_names = [c.name for c in all_courses]
            chosen_name, ok = QInputDialog.getItem(self, "Export Course", "Select Course to export:", c_names, 0, False)
            if not ok or not chosen_name:
                return
            course = next((c for c in all_courses if c.name == chosen_name), None)
            if not course or course.id is None:
                return
            selected_cid = course.id

        course = self.course_repo.get_by_id(selected_cid)
        if not course:
            return

        fmt_choices = ["Morphism DSL (.mdsl)", "Morphism Package (.mpkg)", "Course JSON (.json)"]
        chosen_fmt_str, ok = QInputDialog.getItem(
            self,
            f"Export '{course.name}'",
            "Choose export format:",
            fmt_choices,
            0,
            False,
        )
        if not ok or not chosen_fmt_str:
            return

        if "mdsl" in chosen_fmt_str:
            fmt = "mdsl"
        elif "mpkg" in chosen_fmt_str:
            fmt = "mpkg"
        else:
            fmt = "json"

        self._on_export_course(selected_cid, fmt)

    def _on_export_course(self, course_id: int, fmt: str) -> None:
        course = self.course_repo.get_by_id(course_id)
        if course is None:
            return
        safe_name = course.name.replace(" ", "_").lower()
        export_dir = get_project_root() / "to_export"
        export_dir.mkdir(parents=True, exist_ok=True)
        default_file = str(export_dir / f"{safe_name}.{fmt}")

        if fmt == "mpkg":
            path_str, _ = QFileDialog.getSaveFileName(self, "Export .mpkg Deck", default_file, "Morphism Package (*.mpkg)")
            if path_str:
                self.mpkg_service.export_mpkg(course_id, Path(path_str), include_scheduling=True)
                QMessageBox.information(self, "Export Complete", f"Exported course to '{path_str}'.")
        elif fmt == "json":
            path_str, _ = QFileDialog.getSaveFileName(self, "Export .json Deck", default_file, "JSON (*.json)")
            if path_str:
                self.json_service.export_course_file(course_id, Path(path_str), include_scheduling=True)
                QMessageBox.information(self, "Export Complete", f"Exported course to '{path_str}'.")
        elif fmt == "mdsl":
            path_str, _ = QFileDialog.getSaveFileName(self, "Export .mdsl Source", default_file, "Morphism DSL (*.mdsl)")
            if path_str:
                notes = self.note_repo.list_by_course(course_id, include_children=True)
                edges = self.note_repo.list_edges_by_course(course_id)
                mdsl_str = DSLCompiler.decompile_course(course, notes, edges)
                Path(path_str).write_text(mdsl_str, encoding="utf-8")
                QMessageBox.information(self, "Export Complete", f"Exported course to '{path_str}'.")

    def _on_context_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if item is None:
            return
        kind = item.data(0, self.ITEM_TYPE_ROLE)
        item_id = int(item.data(0, self.ITEM_ID_ROLE))
        menu = QMenu(self)

        if kind == "course":
            open_act = menu.addAction("Open in Graph Explorer")
            study_act = menu.addAction("Auto-Study Course")
            edit_act = menu.addAction("Edit Course Properties...")
            menu.addSeparator()
            exp_mpkg = menu.addAction("Export as .mpkg Package...")
            exp_json = menu.addAction("Export as .json...")
            exp_mdsl = menu.addAction("Decompile to .mdsl...")
            menu.addSeparator()
            del_act = menu.addAction("Delete Course")

            chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
            if chosen == open_act:
                self.event_bus.course_selected.emit(item_id)
                self.event_bus.navigate_to_tab.emit("explorer")
            elif chosen == study_act:
                self._on_auto_study_selected()
            elif chosen == edit_act:
                course = self.course_repo.get_by_id(item_id)
                if course:
                    dlg = CourseEditDialog(self.folder_repo.list_all(), course=course, parent=self)
                    if dlg.exec():
                        with UnitOfWork(self.conn):
                            self.course_repo.update(dlg.course)
                        self.event_bus.courses_updated.emit()
            elif chosen == exp_mpkg:
                self._on_export_course(item_id, "mpkg")
            elif chosen == exp_json:
                self._on_export_course(item_id, "json")
            elif chosen == exp_mdsl:
                self._on_export_course(item_id, "mdsl")
            elif chosen == del_act:
                if QMessageBox.question(self, "Delete Course", "Delete this course and all its notes?") == QMessageBox.StandardButton.Yes:
                    with UnitOfWork(self.conn):
                        self.course_repo.delete(item_id)
                    self.event_bus.courses_updated.emit()
        elif kind == "folder":
            study_f = menu.addAction("Auto-Study Folder")
            sub_f = menu.addAction("New Subfolder...")
            del_f = menu.addAction("Delete Folder")
            chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
            if chosen == study_f:
                self._on_auto_study_selected()
            elif chosen == sub_f:
                self._on_new_folder()
            elif chosen == del_f:
                with UnitOfWork(self.conn):
                    self.folder_repo.delete(item_id)
                self.event_bus.courses_updated.emit()
