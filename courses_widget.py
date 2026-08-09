import os
import shutil
from typing import Optional, Dict
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                               QLabel, QTreeWidget, QTreeWidgetItem, QGroupBox, 
                               QInputDialog, QMessageBox, QFileDialog, QSplitter, QAbstractItemView)
from PySide6.QtCore import Signal, Qt
import course_storage
from models import Course

class CourseTreeWidget(QTreeWidget):
    """Custom QTreeWidget with Drag-and-Drop support for Courses and Folders."""

    item_moved = Signal(dict, str)  # (item_data, target_folder_path)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)

    def dropEvent(self, event):
        target_item = self.itemAt(event.pos())
        dragged_item = self.currentItem()

        if not dragged_item:
            super().dropEvent(event)
            return

        dragged_data = dragged_item.data(0, Qt.UserRole)
        if not dragged_data:
            super().dropEvent(event)
            return

        target_folder_path = ""
        if target_item:
            target_data = target_item.data(0, Qt.UserRole)
            if target_data:
                if target_data.get("is_folder"):
                    target_folder_path = target_data.get("folder_path", "")
                else:
                    target_folder_path = target_data.get("folder_path", "")

        super().dropEvent(event)
        self.item_moved.emit(dragged_data, target_folder_path)


class CoursesWidget(QWidget):
    """Ledger view for managing Courses, Folders, Subfolders, Imports & Exports."""

    course_activated = Signal(str, str)  # (course_name, folder_path)
    course_updated = Signal(str, str)    # (course_name, folder_path)
    course_reschedule_requested = Signal(str, str) # (course_name, folder_path)



    def __init__(self, parent=None):
        super().__init__(parent)
        self.active_course_name: str = ""
        self._setup_ui()
        self.refresh_tree()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)

        # Header Title Bar
        header_layout = QHBoxLayout()
        lbl_title = QLabel("📚 Course Knowledge Bases & Hierarchy")
        lbl_title.setStyleSheet("font-size: 20px; font-weight: bold; color: #38bdf8;")
        header_layout.addWidget(lbl_title)
        header_layout.addStretch()

        btn_import = QPushButton("📥 Import Course JSON")
        btn_import.clicked.connect(self._import_course)
        header_layout.addWidget(btn_import)

        btn_export = QPushButton("📤 Export Course JSON")
        btn_export.clicked.connect(self._export_course)
        header_layout.addWidget(btn_export)

        main_layout.addLayout(header_layout)

        # Main Splitter (Folders & Courses Tree | Course Settings & Quick Actions)
        splitter = QSplitter(Qt.Horizontal)

        # Left Column: Tree Widget for Folders, Subfolders & Courses
        tree_group = QGroupBox("Course Hierarchy (Drag & Drop to Organize)")
        tree_layout = QVBoxLayout(tree_group)

        self.tree = CourseTreeWidget()
        self.tree.setHeaderLabels(["Course / Folder", "Type", "Status"])
        self.tree.setColumnWidth(0, 320)
        self.tree.setColumnWidth(1, 120)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.tree.itemSelectionChanged.connect(self._on_tree_selection_changed)
        self.tree.item_moved.connect(self._on_item_moved)
        tree_layout.addWidget(self.tree)

        splitter.addWidget(tree_group)

        # Right Column: Details & Actions Panel
        info_group = QGroupBox("Selected Item Actions")
        info_layout = QVBoxLayout(info_group)

        self.lbl_selected_title = QLabel("Select a course or folder to manage")
        self.lbl_selected_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #818cf8;")
        info_layout.addWidget(self.lbl_selected_title)

        self.lbl_selected_details = QLabel("Double-click a course to launch its Explorer graph canvas.")
        self.lbl_selected_details.setWordWrap(True)
        info_layout.addWidget(self.lbl_selected_details)

        info_layout.addSpacing(20)

        self.btn_open_explorer = QPushButton("🚀 Open Course Graph Canvas")
        self.btn_open_explorer.setStyleSheet("background-color: #6366f1; color: white; font-weight: bold; padding: 12px;")
        self.btn_open_explorer.clicked.connect(self._open_selected_course)
        info_layout.addWidget(self.btn_open_explorer)

        self.btn_import_raw_notes = QPushButton("📥 Import Raw AI Notes into Course")
        self.btn_import_raw_notes.setStyleSheet("background-color: #0284c7; color: white; font-weight: bold; padding: 10px;")
        self.btn_import_raw_notes.clicked.connect(self._import_raw_notes)
        info_layout.addWidget(self.btn_import_raw_notes)

        self.btn_reschedule_course = QPushButton("🔄 Reschedule Course FSRS State")
        self.btn_reschedule_course.setStyleSheet("background-color: #6366f1; color: white; font-weight: bold; padding: 8px;")
        self.btn_reschedule_course.clicked.connect(self._reschedule_course_clicked)
        info_layout.addWidget(self.btn_reschedule_course)

        self.btn_rename = QPushButton("✏️ Rename Item")
        self.btn_rename.clicked.connect(self._rename_item)
        info_layout.addWidget(self.btn_rename)

        self.btn_delete = QPushButton("🗑 Delete Item")
        self.btn_delete.setStyleSheet("background-color: #991b1b; color: #fca5a5;")
        self.btn_delete.clicked.connect(self._delete_item)
        info_layout.addWidget(self.btn_delete)



        info_layout.addStretch()
        splitter.addWidget(info_group)
        splitter.setSizes([600, 320])
        main_layout.addWidget(splitter, stretch=1)

        # Bottom Bar: + New Course and + New Folder
        bottom_layout = QHBoxLayout()
        
        btn_add_folder = QPushButton("📁 + New Folder")
        btn_add_folder.clicked.connect(self._add_folder)
        bottom_layout.addWidget(btn_add_folder)

        btn_add_course = QPushButton("➕ + New Course")
        btn_add_course.setStyleSheet("background-color: #10b981; color: white; font-weight: bold; font-size: 15px; padding: 10px 20px;")
        btn_add_course.clicked.connect(self._add_course)
        bottom_layout.addWidget(btn_add_course)

        bottom_layout.addStretch()
        main_layout.addLayout(bottom_layout)

    def refresh_tree(self, active_course_name: str = ""):
        if active_course_name:
            self.active_course_name = active_course_name

        self.tree.clear()
        courses_info = course_storage.list_courses_info()

        folder_nodes: Dict[str, QTreeWidgetItem] = {}

        # 1. Build Folders
        folder_infos = [c for c in courses_info if c.get("is_folder")]
        for finfo in sorted(folder_infos, key=lambda x: x["folder_path"]):
            fpath = finfo["folder_path"]
            parts = fpath.split("/")
            curr_path = ""
            for part in parts:
                prev_path = curr_path
                curr_path = f"{curr_path}/{part}".strip("/")
                if curr_path not in folder_nodes:
                    f_item = QTreeWidgetItem([f"📁 {part}", "Folder", ""])
                    f_item.setData(0, Qt.UserRole, {"is_folder": True, "folder_path": curr_path})
                    if prev_path and prev_path in folder_nodes:
                        folder_nodes[prev_path].addChild(f_item)
                    else:
                        self.tree.addTopLevelItem(f_item)
                    folder_nodes[curr_path] = f_item

        # 2. Build Courses
        course_infos = [c for c in courses_info if not c.get("is_folder")]
        for cinfo in sorted(course_infos, key=lambda x: (x["folder_path"], x["name"])):
            cname = cinfo["name"]
            fpath = cinfo["folder_path"]

            status_str = "⭐ Active" if cname == self.active_course_name else ""
            c_item = QTreeWidgetItem([f"📘 {cname}", "Course", status_str])
            c_item.setData(0, Qt.UserRole, {"is_folder": False, "course_name": cname, "folder_path": fpath})

            if fpath and fpath in folder_nodes:
                folder_nodes[fpath].addChild(c_item)
            else:
                self.tree.addTopLevelItem(c_item)

        self.tree.expandAll()

    def _on_item_moved(self, dragged_data: dict, target_folder_path: str):
        """Handle Drag-and-Drop file system reorganization."""
        if not dragged_data:
            return

        if not dragged_data.get("is_folder"):
            cname = dragged_data.get("course_name")
            old_fpath = dragged_data.get("folder_path", "")

            if old_fpath == target_folder_path:
                return

            try:
                # Load course, update folder_path and save
                course = course_storage.load_course(cname, old_fpath)
                course_storage.delete_course(cname, old_fpath)
                course.folder_path = target_folder_path
                course_storage.save_course(course)
                self.refresh_tree(course.name)
            except Exception as e:
                QMessageBox.critical(self, "Move Error", f"Failed to move course: {e}")

    def _on_tree_selection_changed(self):
        items = self.tree.selectedItems()
        if not items:
            self.lbl_selected_title.setText("No item selected")
            self.lbl_selected_details.setText("")
            self.btn_open_explorer.setEnabled(False)
            return

        item = items[0]
        data = item.data(0, Qt.UserRole)
        if not data:
            return

        if data.get("is_folder"):
            fpath = data.get("folder_path", "")
            self.lbl_selected_title.setText(f"Folder: {fpath}")
            self.lbl_selected_details.setText("Contains courses and subfolders.")
            self.btn_open_explorer.setEnabled(False)
            self.btn_import_raw_notes.setEnabled(False)
        else:
            cname = data.get("course_name", "")
            fpath = data.get("folder_path", "")
            self.lbl_selected_title.setText(f"Course: {cname}")
            loc_str = f"Folder: {fpath}" if fpath else "Root level course"
            self.lbl_selected_details.setText(f"{loc_str}\nDouble-click to open in Explorer graph canvas.")
            self.btn_open_explorer.setEnabled(True)
            self.btn_import_raw_notes.setEnabled(True)


    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int):
        data = item.data(0, Qt.UserRole)
        if data and not data.get("is_folder"):
            cname = data.get("course_name")
            fpath = data.get("folder_path", "")
            self.course_activated.emit(cname, fpath)

    def _open_selected_course(self):
        items = self.tree.selectedItems()
        if items:
            data = items[0].data(0, Qt.UserRole)
            if data and not data.get("is_folder"):
                cname = data.get("course_name")
                fpath = data.get("folder_path", "")
                self.course_activated.emit(cname, fpath)

    def _add_course(self):
        parent_folder = ""
        items = self.tree.selectedItems()
        if items:
            data = items[0].data(0, Qt.UserRole)
            if data:
                parent_folder = data.get("folder_path", "") if data.get("is_folder") else data.get("folder_path", "")

        name, ok = QInputDialog.getText(self, "New Course", "Enter Course Name:")
        if ok and name.strip():
            course_name = name.strip()
            course_storage.create_course(course_name, parent_folder)
            self.refresh_tree(course_name)
            self.course_activated.emit(course_name, parent_folder)

    def _add_folder(self):
        parent_folder = ""
        items = self.tree.selectedItems()
        if items:
            data = items[0].data(0, Qt.UserRole)
            if data:
                parent_folder = data.get("folder_path", "") if data.get("is_folder") else data.get("folder_path", "")

        folder_name, ok = QInputDialog.getText(self, "New Folder", "Enter Folder Name:")
        if ok and folder_name.strip():
            new_path = f"{parent_folder}/{folder_name.strip()}".strip("/")
            course_storage.create_folder(new_path)
            self.refresh_tree()

    def _rename_item(self):
        items = self.tree.selectedItems()
        if not items:
            return
        item = items[0]
        data = item.data(0, Qt.UserRole)
        if not data:
            return

        if not data.get("is_folder"):
            old_name = data.get("course_name")
            fpath = data.get("folder_path", "")
            new_name, ok = QInputDialog.getText(self, "Rename Course", "Enter new course name:", text=old_name)
            if ok and new_name.strip() and new_name.strip() != old_name:
                course = course_storage.load_course(old_name, fpath)
                course_storage.delete_course(old_name, fpath)
                course.name = new_name.strip()
                course_storage.save_course(course)
                self.refresh_tree(course.name)
                self.course_activated.emit(course.name, fpath)

    def _delete_item(self):
        items = self.tree.selectedItems()
        if not items:
            return
        item = items[0]
        data = item.data(0, Qt.UserRole)
        if not data:
            return

        if not data.get("is_folder"):
            cname = data.get("course_name")
            fpath = data.get("folder_path", "")
            reply = QMessageBox.question(self, "Confirm Delete", f"Are you sure you want to delete course '{cname}'?",
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                course_storage.delete_course(cname, fpath)
                self.refresh_tree()
        else:
            fpath = data.get("folder_path", "")
            reply = QMessageBox.question(self, "Confirm Delete Folder", f"Are you sure you want to delete folder '{fpath}' and all contents?",
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                dir_path = os.path.join(course_storage.COURSES_DIR, fpath)
                if os.path.exists(dir_path):
                    shutil.rmtree(dir_path, ignore_errors=True)
                self.refresh_tree()

    def _import_course(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "Import Course JSON", "", "JSON Files (*.json)")
        if filepath:
            try:
                course = course_storage.import_course_json(filepath)
                self.refresh_tree(course.name)
                self.course_activated.emit(course.name, course.folder_path)
            except Exception as e:
                QMessageBox.critical(self, "Import Error", f"Failed to import course: {e}")

    def _export_course(self):
        items = self.tree.selectedItems()
        if not items or items[0].data(0, Qt.UserRole).get("is_folder"):
            QMessageBox.warning(self, "Select Course", "Please select a course to export.")
            return

        cname = items[0].data(0, Qt.UserRole).get("course_name")
        fpath = items[0].data(0, Qt.UserRole).get("folder_path", "")
        dest_filepath, _ = QFileDialog.getSaveFileName(self, "Export Course JSON", f"{cname}.json", "JSON Files (*.json)")
        if dest_filepath:
            try:
                course = course_storage.load_course(cname, fpath)
                course_storage.export_course_json(course, dest_filepath)
                QMessageBox.information(self, "Export Successful", f"Course '{cname}' exported to:\n{dest_filepath}")
            except Exception as e:
                QMessageBox.critical(self, "Export Error", f"Failed to export course: {e}")

    def _import_raw_notes(self):
        items = self.tree.selectedItems()
        if not items or items[0].data(0, Qt.UserRole).get("is_folder"):
            QMessageBox.warning(self, "Select Course", "Please select a course to import raw AI notes into.")
            return

        cname = items[0].data(0, Qt.UserRole).get("course_name")
        fpath = items[0].data(0, Qt.UserRole).get("folder_path", "")

        filepath, _ = QFileDialog.getOpenFileName(self, "Import Raw AI Notes JSON", "", "JSON Files (*.json)")
        if filepath:
            try:
                course = course_storage.load_course(cname, fpath)
                n_cnt, c_cnt = course_storage.import_raw_notes_into_course(course, filepath)
                QMessageBox.information(
                    self, 
                    "Import Successful", 
                    f"Successfully imported into '{cname}':\n• {n_cnt} new Notes\n• {c_cnt} total Cards/Steps"
                )
                self.refresh_tree(cname)
                self.course_updated.emit(cname, fpath)
            except Exception as e:
                QMessageBox.critical(self, "Import Raw Notes Error", f"Failed to import raw notes: {e}")

    def _reschedule_course_clicked(self):
        items = self.tree.selectedItems()
        if not items or items[0].data(0, Qt.UserRole).get("is_folder"):
            QMessageBox.warning(self, "Select Course", "Please select a course to reschedule FSRS state.")
            return

        cname = items[0].data(0, Qt.UserRole).get("course_name")
        fpath = items[0].data(0, Qt.UserRole).get("folder_path", "")
        self.course_reschedule_requested.emit(cname, fpath)





