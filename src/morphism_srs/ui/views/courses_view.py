from __future__ import annotations

from pathlib import Path
import sqlite3

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QDragEnterEvent, QDragMoveEvent, QDropEvent, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
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
from morphism_srs.services.import_export.mpkg_service import MpkgService
from morphism_srs.storage.media_vault import MediaVault
from morphism_srs.storage.repositories.course_repo import CourseRepository
from morphism_srs.storage.repositories.folder_repo import FolderRepository
from morphism_srs.storage.repositories.note_repo import NoteRepository
from morphism_srs.storage.unit_of_work import UnitOfWork
from morphism_srs.theming.delegates import set_widget_props
from morphism_srs.ui.dialogs.custom_study_dialog import CustomStudyDialog
from morphism_srs.ui.window_sizing import wrap_in_scroll_area


class CourseEditDialog(QDialog):
    def __init__(
        self,
        folders: list[CourseFolderModel],
        course: CourseModel | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.course = course or CourseModel(name="")
        self.setWindowTitle("Edit Course" if course else "New Course")
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.name_edit = QLineEdit(self.course.name, self)
        form.addRow("Course Name:", self.name_edit)

        self.folder_combo = QComboBox(self)
        self.folder_combo.addItem("(None / Root)", None)
        for f in folders:
            self.folder_combo.addItem(f"📁 {f.name}", f.id)
            if self.course.folder_id == f.id:
                self.folder_combo.setCurrentIndex(self.folder_combo.count() - 1)
        form.addRow("Folder:", self.folder_combo)

        self.color_edit = QLineEdit(self.course.color_hex, self)
        form.addRow("Color Hex:", self.color_edit)

        self.desc_edit = QLineEdit(self.course.description, self)
        form.addRow("Description:", self.desc_edit)

        self.retention_edit = QLineEdit(str(self.course.desired_retention), self)
        form.addRow("Desired Retention:", self.retention_edit)

        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Invalid Name", "Course name cannot be empty.")
            return
        self.course.name = name
        self.course.folder_id = self.folder_combo.currentData()
        self.course.color_hex = self.color_edit.text().strip() or "#89b4fa"
        self.course.description = self.desc_edit.text().strip()
        try:
            self.course.desired_retention = float(self.retention_edit.text().strip())
        except ValueError:
            self.course.desired_retention = 0.80
        self.accept()


class CoursesTreeWidget(QTreeWidget):
    """TreeWidget supporting Drag & Drop re-parenting of Courses into Folders and Folders into Folders/Root."""

    itemMoved = Signal(str, int, object)  # (item_type: str, item_id: int, new_parent_id: int | None)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.source() is self:
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.source() is self:
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        if event.source() is not self:
            super().dropEvent(event)
            return

        selected_items = self.selectedItems()
        if not selected_items:
            event.ignore()
            return

        dragged_item = selected_items[0]
        item_type = dragged_item.data(0, Qt.ItemDataRole.UserRole)
        item_id = dragged_item.data(0, Qt.ItemDataRole.UserRole + 1)

        if not item_type or item_id is None:
            event.ignore()
            return

        target_item = self.itemAt(event.position().toPoint())
        target_folder_id: int | None = None

        if target_item is not None:
            if target_item is dragged_item:
                event.ignore()
                return

            target_type = target_item.data(0, Qt.ItemDataRole.UserRole)
            target_id = target_item.data(0, Qt.ItemDataRole.UserRole + 1)

            if target_type == "folder":
                target_folder_id = int(target_id)
            elif target_type == "course":
                parent_it = target_item.parent()
                if parent_it is not None and parent_it.data(0, Qt.ItemDataRole.UserRole) == "folder":
                    target_folder_id = int(parent_it.data(0, Qt.ItemDataRole.UserRole + 1))
                else:
                    target_folder_id = None
        else:
            target_folder_id = None

        # Cycle prevention for folders
        if item_type == "folder":
            curr = target_item
            while curr is not None:
                if curr is dragged_item:
                    event.ignore()
                    return
                curr = curr.parent()

        event.acceptProposedAction()
        self.itemMoved.emit(str(item_type), int(item_id), target_folder_id)


class CoursesView(QWidget):
    """Hierarchical Folder & Course Tree View with dedicated sidebar for folder/deck management and streamlined top bar."""

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

        # Clean streamlined header row: only Title, Custom Study, and Auto-Study
        header_row = QHBoxLayout()
        title = QLabel("Courses & Knowledge Folders", container)
        set_widget_props(title, role="title")
        header_row.addWidget(title)
        header_row.addStretch(1)

        custom_study_btn = QPushButton("Custom Study...", container)
        set_widget_props(custom_study_btn, variant="ghost")
        custom_study_btn.clicked.connect(self._on_custom_study_selected)
        header_row.addWidget(custom_study_btn)

        auto_study_btn = QPushButton("Auto-Study Due", container)
        set_widget_props(auto_study_btn, variant="primary")
        auto_study_btn.setToolTip("Secondary mode: queue due cards automatically (Primary mode is clicking nodes in Graph Explorer)")
        auto_study_btn.clicked.connect(self._on_auto_study_selected)
        header_row.addWidget(auto_study_btn)

        root.addLayout(header_row)

        # Main Body: Tree on Left + Sidebar on Right
        body_row = QHBoxLayout()
        body_row.setSpacing(14)

        self.tree = CoursesTreeWidget(container)
        self.tree.setMinimumHeight(260)
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["Folder / Course", "Notes", "Cards", "Due Now", "New"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 5):
            self.tree.header().setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.tree.itemMoved.connect(self._on_item_moved)
        body_row.addWidget(self.tree, 1)

        sidebar = QFrame(container)
        set_widget_props(sidebar, role="panel")
        sidebar.setFixedWidth(190)
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(10, 12, 10, 12)
        sb_layout.setSpacing(8)

        sb_title = QLabel("<b>Deck Actions</b>", sidebar)
        sb_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sb_layout.addWidget(sb_title)
        sb_layout.addSpacing(4)

        new_folder_btn = QPushButton("+ New Folder", sidebar)
        new_folder_btn.clicked.connect(self._on_new_folder)
        sb_layout.addWidget(new_folder_btn)

        new_course_btn = QPushButton("+ New Course", sidebar)
        new_course_btn.clicked.connect(self._on_new_course)
        sb_layout.addWidget(new_course_btn)

        sb_layout.addSpacing(6)

        import_btn = QPushButton("📥 Import Deck...", sidebar)
        import_btn.setToolTip("Import .mdsl or .mpkg packages")
        import_btn.clicked.connect(self._on_import_deck)
        sb_layout.addWidget(import_btn)

        export_btn = QPushButton("📤 Export Course...", sidebar)
        export_btn.setToolTip("Export course as .mpkg package or .mdsl")
        export_btn.clicked.connect(self._on_export_button_clicked)
        sb_layout.addWidget(export_btn)

        sb_layout.addStretch(1)
        body_row.addWidget(sidebar)

        root.addLayout(body_row, 1)

        scroll = wrap_in_scroll_area(container, self, min_width=640, min_height=420)
        outer.addWidget(scroll)

    def _on_item_moved(self, item_type: str, item_id: int, target_folder_id: int | None) -> None:
        if item_type == "course":
            course = self.course_repo.get_by_id(item_id)
            if course and course.folder_id != target_folder_id:
                course.folder_id = target_folder_id
                with UnitOfWork(self.conn):
                    self.course_repo.update(course)
                self.event_bus.courses_updated.emit()
        elif item_type == "folder":
            folder = self.folder_repo.get_by_id(item_id)
            if folder and folder.parent_id != target_folder_id:
                folder.parent_id = target_folder_id
                with UnitOfWork(self.conn):
                    self.folder_repo.update(folder)
                self.event_bus.courses_updated.emit()

    def refresh_tree(self) -> None:
        self.tree.clear()
        folders = self.folder_repo.list_all()
        courses = self.course_repo.list_all()
        counts = self.course_repo.get_course_counts()

        folder_items: dict[int, QTreeWidgetItem] = {}
        for f in folders:
            item = QTreeWidgetItem()
            item.setText(0, f"📁 {f.name}")
            item.setData(0, self.ITEM_TYPE_ROLE, "folder")
            item.setData(0, self.ITEM_ID_ROLE, f.id)
            font = QFont()
            font.setBold(True)
            item.setFont(0, font)
            folder_items[f.id or 0] = item

        for f in folders:
            f_item = folder_items[f.id or 0]
            if f.parent_id and f.parent_id in folder_items:
                folder_items[f.parent_id].addChild(f_item)
            else:
                self.tree.addTopLevelItem(f_item)

        for c in courses:
            c_cnt = counts.get(c.id or 0, {"notes": 0, "cards": 0, "due": 0, "new": 0})
            c_item = QTreeWidgetItem()
            c_item.setText(0, f"📘 {c.name}")
            c_item.setData(0, self.ITEM_TYPE_ROLE, "course")
            c_item.setData(0, self.ITEM_ID_ROLE, c.id)

            c_item.setText(1, str(c_cnt["notes"]))
            c_item.setText(2, str(c_cnt["cards"]))
            c_item.setText(3, str(c_cnt["due"]))
            c_item.setText(4, str(c_cnt["new"]))

            if c_cnt["due"] > 0:
                c_item.setForeground(3, QColor("#ef4444"))
                c_item.setText(3, f"🔴 {c_cnt['due']}")

            if c.folder_id and c.folder_id in folder_items:
                folder_items[c.folder_id].addChild(c_item)
            else:
                self.tree.addTopLevelItem(c_item)

        self.tree.expandAll()

    def _selected_type_and_id(self) -> tuple[str | None, int | None]:
        sel = self.tree.selectedItems()
        if not sel:
            return None, None
        it = sel[0]
        return str(it.data(0, self.ITEM_TYPE_ROLE)), it.data(0, self.ITEM_ID_ROLE)

    def _on_item_double_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        kind = item.data(0, self.ITEM_TYPE_ROLE)
        item_id = item.data(0, self.ITEM_ID_ROLE)
        if kind == "course" and item_id is not None:
            self.event_bus.course_selected.emit(int(item_id))
            self.event_bus.navigate_to_tab.emit("explorer")

    def _on_new_folder(self) -> None:
        name, ok = QInputDialog.getText(self, "New Folder", "Folder Name:")
        if ok and name.strip():
            kind, item_id = self._selected_type_and_id()
            parent_id = int(item_id) if kind == "folder" and item_id is not None else None
            with UnitOfWork(self.conn):
                self.folder_repo.create(CourseFolderModel(name=name.strip(), parent_id=parent_id))
            self.event_bus.courses_updated.emit()

    def _on_new_course(self) -> None:
        kind, item_id = self._selected_type_and_id()
        folder_id = int(item_id) if kind == "folder" and item_id is not None else None
        folders = self.folder_repo.list_all()
        dlg = CourseEditDialog(folders, parent=self)
        if folder_id is not None:
            # Preselect current folder
            for idx in range(dlg.folder_combo.count()):
                if dlg.folder_combo.itemData(idx) == folder_id:
                    dlg.folder_combo.setCurrentIndex(idx)
                    break
        if dlg.exec():
            with UnitOfWork(self.conn):
                created = self.course_repo.create(dlg.course)
            self.event_bus.courses_updated.emit()
            if created.id:
                self.event_bus.course_selected.emit(created.id)

    def _on_move_course_dialog(self, course_id: int) -> None:
        course = self.course_repo.get_by_id(course_id)
        if not course:
            return
        folders = self.folder_repo.list_all()
        options = ["(Root / No Folder)"] + [f"📁 {f.name}" for f in folders]
        current_idx = 0
        if course.folder_id is not None:
            for i, f in enumerate(folders):
                if f.id == course.folder_id:
                    current_idx = i + 1
                    break
        chosen, ok = QInputDialog.getItem(
            self,
            "Move Course to Folder",
            f"Select destination folder for '{course.name}':",
            options,
            current_idx,
            False,
        )
        if ok and chosen:
            if chosen == "(Root / No Folder)":
                target_fid = None
            else:
                idx = options.index(chosen) - 1
                target_fid = folders[idx].id
            course.folder_id = target_fid
            with UnitOfWork(self.conn):
                self.course_repo.update(course)
            self.event_bus.courses_updated.emit()

    def _on_move_folder_dialog(self, folder_id: int) -> None:
        folder = self.folder_repo.get_by_id(folder_id)
        if not folder:
            return
        all_folders = self.folder_repo.list_all()
        candidate_folders = [f for f in all_folders if f.id != folder_id]
        options = ["(Root / Top Level)"] + [f"📁 {f.name}" for f in candidate_folders]
        current_idx = 0
        if folder.parent_id is not None:
            for i, f in enumerate(candidate_folders):
                if f.id == folder.parent_id:
                    current_idx = i + 1
                    break
        chosen, ok = QInputDialog.getItem(
            self,
            "Move Folder",
            f"Select parent destination for folder '{folder.name}':",
            options,
            current_idx,
            False,
        )
        if ok and chosen:
            if chosen == "(Root / Top Level)":
                target_pid = None
            else:
                idx = options.index(chosen) - 1
                target_pid = candidate_folders[idx].id
            folder.parent_id = target_pid
            with UnitOfWork(self.conn):
                self.folder_repo.update(folder)
            self.event_bus.courses_updated.emit()

    def _on_auto_study_selected(self) -> None:
        kind, item_id = self._selected_type_and_id()
        cids: list[int] = []
        if kind == "course" and item_id is not None:
            cids = [int(item_id)]
        elif kind == "folder" and item_id is not None:
            cids = [c.id for c in self.course_repo.list_by_folder_recursive(int(item_id)) if c.id is not None]

        cnt = self.review_controller.start_auto_study(course_ids=cids or None)
        if cnt == 0:
            QMessageBox.information(self, "All Caught Up", "There are no due cards in this selection.")
            return
        self.event_bus.navigate_to_tab.emit("review")

    def _on_custom_study_selected(self) -> None:
        kind, item_id = self._selected_type_and_id()
        cids: list[int] = []
        if kind == "course" and item_id is not None:
            cids = [int(item_id)]
        elif kind == "folder" and item_id is not None:
            cids = [c.id for c in self.course_repo.list_by_folder_recursive(int(item_id)) if c.id is not None]

        dlg = CustomStudyDialog(self.conn, initial_course_ids=cids, parent=self)
        if dlg.exec():
            cfg = dlg.build_config()
            cnt = self.review_controller.start_custom_study(cfg)
            if cnt == 0:
                QMessageBox.information(self, "Empty Queue", "No cards matched your Custom Study filters.")
                return
            self.event_bus.navigate_to_tab.emit("review")

    def _on_import_deck(self) -> None:
        to_import_dir = get_project_root() / "to_import"
        start_dir = str(to_import_dir) if to_import_dir.exists() else ""
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Import Morphism Deck (.mdsl / .mpkg)",
            start_dir,
            "Morphism Decks (*.mdsl *.mpkg)",
        )
        if not path_str:
            return
        p = Path(path_str)
        kind, item_id = self._selected_type_and_id()
        selected_course_id = int(item_id) if kind == "course" and item_id is not None else None
        try:
            if p.suffix.lower() == ".mpkg":
                cid = self.mpkg_service.import_mpkg(p, include_scheduling=True)
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

        fmt_choices = ["Morphism DSL (.mdsl)", "Morphism Package (.mpkg)"]
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

        fmt = "mpkg" if "mpkg" in chosen_fmt_str else "mdsl"
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
            move_act = menu.addAction("📁 Move to Folder...")
            menu.addSeparator()
            exp_mpkg = menu.addAction("Export as .mpkg Package...")
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
            elif chosen == move_act:
                self._on_move_course_dialog(item_id)
            elif chosen == exp_mpkg:
                self._on_export_course(item_id, "mpkg")
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
            move_f = menu.addAction("📁 Move Folder...")
            del_f = menu.addAction("Delete Folder")
            chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
            if chosen == study_f:
                self._on_auto_study_selected()
            elif chosen == sub_f:
                self._on_new_folder()
            elif chosen == move_f:
                self._on_move_folder_dialog(item_id)
            elif chosen == del_f:
                with UnitOfWork(self.conn):
                    self.folder_repo.delete(item_id)
                self.event_bus.courses_updated.emit()
