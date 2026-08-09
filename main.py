import sys
import os
import ctypes
from typing import List, Dict, Optional
from datetime import datetime, timezone
from PySide6.QtWidgets import (QApplication, QMainWindow, QStackedWidget, 
                               QToolBar, QWidget, QVBoxLayout, QHBoxLayout, 
                               QLabel, QPushButton, QMessageBox, QInputDialog, QTabBar,
                               QDialog, QListWidget, QListWidgetItem)

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QAction, QIcon

from models import Course, NoteNode, NoteEdge, Flashcard, ProofSequenceCard, ReviewLogRecord
from scheduler_manager import SchedulerManager
from graph_view import GraphWidget
from review_view import ReviewWidget
from node_editor_dialog import NodeEditorDialog
from retrievability_plot_dialog import RetrievabilityPlotDialog
from courses_widget import CoursesWidget
from stats_widget import StatsWidget
import course_storage
from styles import DARK_THEME_QSS
from fsrs import Rating

class DeletePrereqsDialog(QDialog):
    """Dialog allowing user to selectively remove prerequisite edges attached to a note."""
    def __init__(self, note: NoteNode, edges: List[NoteEdge], notes_map: Dict[str, NoteNode], parent=None):
        super().__init__(parent)
        self.note = note
        self.edges = edges
        self.notes_map = notes_map
        self.selected_edges_to_delete: List[NoteEdge] = []

        self.setWindowTitle(f"✂️ Remove Prerequisites - '{note.title}'")
        self.resize(520, 360)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        lbl_desc = QLabel(f"Select prerequisite connections attached to '{self.note.title}' to remove:")
        lbl_desc.setStyleSheet("font-size: 13px; font-weight: bold; color: #38bdf8;")
        layout.addWidget(lbl_desc)

        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet("QListWidget { background-color: #0f172a; border: 1px solid #334155; border-radius: 8px; font-size: 13px; padding: 6px; } QListWidget::item { padding: 6px; }")

        self.attached_edges = [
            e for e in self.edges if e.source_id == self.note.note_id or e.target_id == self.note.note_id
        ]

        for edge in self.attached_edges:
            src_note = self.notes_map.get(edge.source_id)
            tgt_note = self.notes_map.get(edge.target_id)
            src_name = src_note.title if src_note else f"ID {edge.source_id}"
            tgt_name = tgt_note.title if tgt_note else f"ID {edge.target_id}"

            if edge.target_id == self.note.note_id:
                label = f"📥 Incoming: '{src_name}' ➔ '{self.note.title}'"
            else:
                label = f"📤 Outgoing: '{self.note.title}' ➔ '{tgt_name}'"

            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            item.setData(Qt.UserRole, edge)
            self.list_widget.addItem(item)

        layout.addWidget(self.list_widget)

        btn_layout = QHBoxLayout()
        btn_select_all = QPushButton("Select All")
        btn_select_all.clicked.connect(self._select_all)
        btn_layout.addWidget(btn_select_all)

        btn_layout.addStretch()

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        btn_delete = QPushButton("✂️ Remove Selected")
        btn_delete.setStyleSheet("background-color: #dc2626; color: white; font-weight: bold; padding: 6px 14px; border-radius: 6px;")
        btn_delete.clicked.connect(self._on_delete)
        btn_layout.addWidget(btn_delete)

        layout.addLayout(btn_layout)

    def _select_all(self):
        for i in range(self.list_widget.count()):
            self.list_widget.item(i).setCheckState(Qt.Checked)

    def _on_delete(self):
        self.selected_edges_to_delete = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.Checked:
                self.selected_edges_to_delete.append(item.data(Qt.UserRole))

        if not self.selected_edges_to_delete:
            QMessageBox.warning(self, "No Selection", "Please check at least one prerequisite edge to remove.")
            return

        self.accept()


class MainWindow(QMainWindow):
    """Morphism SRS - Main window with Top Ledger Navigation (Courses, Explorer, Review, Stats)."""


    def __init__(self):
        super().__init__()
        if os.path.exists("icon.ico"):
            self.setWindowIcon(QIcon("icon.ico"))

        self.scheduler_manager = SchedulerManager()
        self.current_course: Course = None

        self.current_review_queue: List[object] = []
        self.current_review_note: Optional[NoteNode] = None
        self.serial_past_steps: List[object] = []

        self._init_data()
        self._setup_ui()

    def _init_data(self):
        """Ensure seed courses exist and load default course."""
        course_storage.ensure_seed_courses()
        cinfo_list = [c for c in course_storage.list_courses_info() if not c.get("is_folder")]
        initial_name = cinfo_list[0]["name"] if cinfo_list else "My Course"
        initial_folder = cinfo_list[0]["folder_path"] if cinfo_list else ""
        self.current_course = course_storage.load_course(initial_name, initial_folder)


    @property
    def notes(self) -> List[NoteNode]:
        return self.current_course.notes if self.current_course else []

    @property
    def edges(self) -> List[NoteEdge]:
        return self.current_course.edges if self.current_course else []

    def _update_title(self):
        cname = self.current_course.name if self.current_course else "Default"
        self.setWindowTitle(f"Morphism SRS - Course: {cname}")

    def _setup_ui(self):
        self.setStyleSheet(DARK_THEME_QSS)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 1. Top Ledger Navigation Bar
        ledger_bar = QHBoxLayout()
        ledger_bar.setContentsMargins(12, 6, 12, 6)

        self.tab_bar = QTabBar()
        self.tab_bar.setStyleSheet("""
            QTabBar::tab {
                background: #1e293b;
                color: #94a3b8;
                padding: 10px 24px;
                font-size: 14px;
                font-weight: bold;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                margin-right: 4px;
            }
            QTabBar::tab:selected {
                background: #6366f1;
                color: #ffffff;
            }
            QTabBar::tab:hover:!selected {
                background: #334155;
                color: #f8fafc;
            }
        """)

        self.tab_bar.addTab("📚 Courses")
        self.tab_bar.addTab("🗺️ Explorer")
        self.tab_bar.addTab("📝 Review")
        self.tab_bar.addTab("📈 Stats")
        self.tab_bar.currentChanged.connect(self._on_ledger_tab_changed)

        ledger_bar.addWidget(self.tab_bar)
        ledger_bar.addStretch()

        self.lbl_active_course_badge = QLabel(f"Active: {self.current_course.name}")
        self.lbl_active_course_badge.setStyleSheet("font-size: 14px; font-weight: bold; color: #38bdf8; background: #0f172a; padding: 6px 14px; border-radius: 6px; border: 1px solid #334155;")
        ledger_bar.addWidget(self.lbl_active_course_badge)

        main_layout.addLayout(ledger_bar)

        # 2. Main Stacked Router View Pages
        self.stack = QStackedWidget()
        main_layout.addWidget(self.stack, stretch=1)

        # Page 0: Courses Ledger Widget
        self.courses_widget = CoursesWidget()
        self.courses_widget.course_activated.connect(self._on_course_activated_from_ledger)
        self.courses_widget.course_updated.connect(self._on_course_updated_from_ledger)
        self.courses_widget.course_reschedule_requested.connect(self._reschedule_course)
        self.stack.addWidget(self.courses_widget)

        # Page 1: Explorer View Container (Graph View + Side Controls)
        explorer_container = QWidget()
        explorer_layout = QHBoxLayout(explorer_container)
        explorer_layout.setContentsMargins(0, 0, 0, 0)
        explorer_layout.setSpacing(0)

        self.graph_view = GraphWidget(self.notes, self.edges, scheduler_manager=self.scheduler_manager)
        self.graph_view.signals.note_selected_for_review.connect(self.start_note_review)
        self.graph_view.signals.note_edit_requested.connect(self._edit_note_dialog)
        self.graph_view.signals.note_info_requested.connect(self._open_note_info_dialog)
        self.graph_view.signals.note_reschedule_requested.connect(self._reschedule_note)
        self.graph_view.signals.note_force_review_requested.connect(self._force_review_note)
        self.graph_view.signals.note_delete_prereqs_requested.connect(self._delete_prereqs_dialog)
        self.graph_view.signals.note_delete_requested.connect(self._delete_note_dialog)

        self.graph_view.signals.prereq_edge_created.connect(self._on_prereq_edge_created)


        explorer_layout.addWidget(self.graph_view, stretch=1)

        # Explorer Toolbar
        explorer_toolbar = QToolBar("Explorer Controls")
        explorer_toolbar.setOrientation(Qt.Vertical)
        explorer_toolbar.setIconSize(QSize(18, 18))

        act_add_note = QAction("+ New Note", self)
        act_add_note.triggered.connect(self._create_new_note)
        explorer_toolbar.addAction(act_add_note)

        act_auto_layout = QAction("⚡ Auto Layout", self)
        act_auto_layout.triggered.connect(self._auto_arrange_graph)
        explorer_toolbar.addAction(act_auto_layout)

        # Snapping Mode Toggle Button (Green when active)
        self.btn_snap_toggle = QPushButton("🧲 Snapping Off")
        self.btn_snap_toggle.setCheckable(True)
        self.btn_snap_toggle.setStyleSheet("background-color: #1e293b; color: #94a3b8; padding: 6px 10px; font-weight: bold; border-radius: 6px;")
        self.btn_snap_toggle.toggled.connect(self._on_snap_toggled)
        explorer_toolbar.addWidget(self.btn_snap_toggle)

        act_save = QAction("💾 Save", self)
        act_save.triggered.connect(self.save_data)
        explorer_toolbar.addAction(act_save)

        explorer_layout.addWidget(explorer_toolbar)

        self.stack.addWidget(explorer_container)

        # Page 2: Review Window
        self.review_view = ReviewWidget(self.scheduler_manager)
        self.review_view.back_to_graph_requested.connect(lambda: self.tab_bar.setCurrentIndex(1))
        self.review_view.rated.connect(self._on_card_rated)
        self.stack.addWidget(self.review_view)

        # Page 3: Stats View
        self.stats_widget = StatsWidget(self.scheduler_manager)
        self.stack.addWidget(self.stats_widget)

        # Set default tab to Courses (0) or Explorer (1)
        self.tab_bar.setCurrentIndex(1)
        self._update_title()

    def _on_ledger_tab_changed(self, index: int):
        self.stack.setCurrentIndex(index)
        if index == 0:
            self.courses_widget.refresh_tree(self.current_course.name if self.current_course else "")
        elif index == 1:
            if self.current_course:
                try:
                    self.current_course = course_storage.load_course(self.current_course.name, self.current_course.folder_path)
                    self.graph_view.load_graph(self.notes, self.edges)
                except Exception as e:
                    print(f"Warning reloading active course: {e}")
            else:
                self.graph_view.refresh_nodes()
        elif index == 2:
            if not self.current_review_queue and not self.current_review_note:
                self.review_view.show_empty_session()
        elif index == 3:
            if self.current_course:
                self.stats_widget.load_course_stats(self.current_course)

    def _on_course_updated_from_ledger(self, course_name: str, folder_path: str):
        """Handle course file update on disk (e.g. raw notes import). Reload active course if matched."""
        if self.current_course and self.current_course.name == course_name:
            try:
                self.current_course = course_storage.load_course(course_name, folder_path)
                self.graph_view.load_graph(self.notes, self.edges)
            except Exception as e:
                print(f"Error updating active course after disk modification: {e}")



    def _on_course_activated_from_ledger(self, course_name: str, folder_path: str):
        # Only save previous course if switching to a DIFFERENT course
        if self.current_course and self.current_course.name != course_name:
            self.save_data(silent=True)

        try:
            self.current_course = course_storage.load_course(course_name, folder_path)

            self.graph_view.load_graph(self.notes, self.edges)
            self.lbl_active_course_badge.setText(f"Active: {self.current_course.name}")
            self._update_title()
            # Switch to Explorer tab
            self.tab_bar.setCurrentIndex(1)
        except Exception as e:
            QMessageBox.critical(self, "Error Loading Course", f"Failed to load course '{course_name}': {e}")

    def start_note_review(self, note: NoteNode):
        """Start or queue a review session for a note."""
        if not note.cards:
            QMessageBox.information(self, "No Cards to Review", f"Note '{note.title}' does not contain any cards. Please edit the note to add cards.")
            return

        if note.is_serial_sequence_single():

            # Find index of first due/unreviewed step
            now_dt = datetime.now(timezone.utc)
            first_due_idx = 0
            for idx, c in enumerate(note.cards):
                if c.fsrs_card.last_review is None or c.is_due():
                    first_due_idx = idx
                    break
            else:
                if note.cards:
                    first_due_idx = min(range(len(note.cards)), key=lambda i: self.scheduler_manager.get_card_retrievability(note.cards[i], now_dt))

            # Queue all cards from first_due_idx onwards that are due/unreviewed
            due_queue = [c for c in note.cards[first_due_idx:] if (c.fsrs_card.last_review is None or c.is_due())]
            if not due_queue and note.cards:
                due_queue = [note.cards[first_due_idx]]

            self.current_review_note = note
            self.current_review_queue = list(due_queue)
            self.serial_past_steps = list(note.cards[:first_due_idx])
            self.tab_bar.setCurrentIndex(2)  # Switch to Review Tab
            self._next_review_card()
            return


        if note.is_serial_sequence_full():
            self.current_review_note = note
            self.current_review_queue = list(note.cards)
            self.serial_past_steps = []
            self.tab_bar.setCurrentIndex(2)  # Switch to Review Tab
            self._next_review_card()
            return

        # Regular Note: Partial Retention Scheduling logic
        # Sort cards ascending by retrievability R_i(t)
        now_dt = datetime.now(timezone.utc)
        sorted_cards = sorted(note.cards, key=lambda c: self.scheduler_manager.get_card_retrievability(c, now_dt))
        
        cards_to_review = []
        prod_r = 1.0
        for c in sorted_cards:
            prod_r *= self.scheduler_manager.get_card_retrievability(c, now_dt)

        # If joint retention <= desired_retention or any card is unreviewed (New)
        if prod_r <= note.desired_retention or any(c.fsrs_card.last_review is None for c in note.cards):
            # Select lowest retrievability cards required to restore joint retention
            accum_prod = 1.0
            for c in sorted_cards:
                cards_to_review.append(c)
                # If reviewing selected cards restores target R, stop queuing
                if c.fsrs_card.last_review is not None:
                    sim_prod = accum_prod * 1.0  # assume 100% retrievability after review
                    remaining_prod = 1.0
                    for rem_c in sorted_cards[len(cards_to_review):]:
                        remaining_prod *= self.scheduler_manager.get_card_retrievability(rem_c, now_dt)
                    if sim_prod * remaining_prod >= note.desired_retention:
                        break

        if not cards_to_review:
            cards_to_review = note.cards

        self.current_review_note = note
        self.current_review_queue = list(cards_to_review)
        self.serial_past_steps = []
        self.tab_bar.setCurrentIndex(2)  # Switch to Review Tab
        self._next_review_card()

    def _force_review_note(self, note: NoteNode):
        """Force review session for all cards in a note, regardless of FSRS due state."""
        if not note.cards:
            QMessageBox.information(self, "No Cards", f"Note '{note.title}' contains no cards to review.")
            return

        self.current_review_note = note
        self.current_review_queue = list(note.cards)
        self.serial_past_steps = []
        self.tab_bar.setCurrentIndex(2)  # Switch to Review Tab
        self._next_review_card()


    def _start_global_review(self):
        """Start reviewing all due cards across notes in active course."""
        all_due = []
        for note in self.notes:
            if note.is_due(self.scheduler_manager):
                all_due.extend(note.cards)
        
        if not all_due:
            QMessageBox.information(self, "All Complete", f"🎉 Great job! No notes are currently due for review in '{self.current_course.name}'.")
            return

        self.current_review_note = None
        self.current_review_queue = all_due
        self.serial_past_steps = []
        self.tab_bar.setCurrentIndex(2)  # Switch to Review Tab
        self._next_review_card()

    def _next_review_card(self):
        if not self.current_review_queue:
            self.review_view.show_empty_session()
            self.current_review_note = None
            QMessageBox.information(self, "Review Session Completed", "✓ You have completed all due cards in this session!")
            self.save_data(silent=True)
            self.tab_bar.setCurrentIndex(1)  # Return to Explorer
            return

        current_card = self.current_review_queue[0]
        if self.current_review_note and self.current_review_note.is_serial_sequence():
            step_idx = len(self.serial_past_steps) + 1
            total_steps = len(self.current_review_note.cards)
            joint_r = self.current_review_note.get_joint_retention(self.scheduler_manager)
            seq_info = {
                "step_idx": step_idx,
                "total_steps": total_steps,
                "past_steps": self.serial_past_steps,
                "note_title": self.current_review_note.title,
                "joint_retention": joint_r
            }
            self.review_view.load_object(current_card, seq_info)
        else:
            self.review_view.load_object(current_card)

    def _on_card_rated(self, rating: Rating):
        """Called when user submits a rating for current card."""
        if self.current_review_queue:
            rated_card = self.current_review_queue[0]
            
            # Record FSRS review log event for optimization
            fc = rated_card.fsrs_card
            log_rec = ReviewLogRecord(
                card_id=rated_card.item_id,
                rating=int(rating.value) if hasattr(rating, "value") else int(rating),
                review_time=datetime.now(timezone.utc).isoformat(),
                elapsed_days=getattr(fc, "elapsed_days", 0),
                scheduled_days=getattr(fc, "scheduled_days", 0),
                state=getattr(fc.state, "value", 0) if hasattr(fc, "state") else 0,
                stability=getattr(fc, "stability", None),
                difficulty=getattr(fc, "difficulty", None)
            )
            course_storage.save_review_log(self.current_course.name, log_rec)
            self.save_data(silent=True)
            if self.current_course:
                self.stats_widget.load_course_stats(self.current_course)

            if self.current_review_note and self.current_review_note.is_serial_sequence():

                if rating == Rating.Again:
                    # Retry step A_j without advancing
                    pass
                else:
                    self.current_review_queue.pop(0)
                    self.serial_past_steps.append(rated_card)
            else:
                self.current_review_queue.pop(0)

            self._next_review_card()

    def _reschedule_note(self, note: NoteNode):
        """Replay all historical review logs to recalculate FSRS state for a note."""
        if not self.current_course: return
        logs = course_storage.load_review_logs(self.current_course.name)
        c_cnt, l_cnt = self.scheduler_manager.reschedule_note(note, logs)
        self.save_data(silent=True)
        self.graph_view.refresh_nodes()
        QMessageBox.information(
            self,
            "Reschedule Completed",
            f"✓ Successfully recalculated FSRS state for note '{note.title}'!\n"
            f"• Cards recalculated: {c_cnt}\n"
            f"• Historical review logs replayed: {l_cnt}"
        )

    def _reschedule_course(self, course_name: str, folder_path: str):
        """Replay all historical review logs to recalculate FSRS state for an entire course."""
        try:
            course = course_storage.load_course(course_name, folder_path)
            logs = course_storage.load_review_logs(course_name)
            c_cnt, l_cnt = self.scheduler_manager.reschedule_course(course, logs)
            course_storage.save_course(course)
            if self.current_course and self.current_course.name == course_name:
                self.current_course = course
                self.graph_view.load_graph(self.notes, self.edges)
            QMessageBox.information(
                self,
                "Reschedule Completed",
                f"✓ Successfully recalculated FSRS state for course '{course_name}'!\n"
                f"• Total Cards recalculated: {c_cnt}\n"
                f"• Total Historical review logs replayed: {l_cnt}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Reschedule Error", f"Failed to reschedule course: {e}")


    def _create_new_note(self):
        """Add a new Note node to graph canvas."""
        title, ok = QInputDialog.getText(self, "New Note Node", "Enter Note Title:")
        if ok and title.strip():
            new_note = NoteNode(title=title.strip(), x=0, y=0)

            dialog = NodeEditorDialog(new_note, self)
            if dialog.exec():
                self.notes.append(new_note)
                self.graph_view.load_graph(self.notes, self.edges)
                self.save_data(silent=True)

    def _edit_note_dialog(self, note: NoteNode):
        """Edit an existing note."""
        dialog = NodeEditorDialog(note, self)
        if dialog.exec():
            self.graph_view.load_graph(self.notes, self.edges)
            self.save_data(silent=True)

    def _open_note_info_dialog(self, note: NoteNode):
        """Open retrievability plot info dialog for a specific note."""
        if not self.current_course: return
        dialog = RetrievabilityPlotDialog(self.current_course, self.scheduler_manager, initial_note=note, parent=self)
        dialog.exec()

    def _delete_note_dialog(self, note: NoteNode):
        """Delete a note node and its attached prerequisite edges."""
        reply = QMessageBox.question(self, "Confirm Delete Note", f"Are you sure you want to delete note '{note.title}' and all its connections?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.current_course.notes = [n for n in self.notes if n.note_id != note.note_id]
            self.current_course.edges = [e for e in self.edges if e.source_id != note.note_id and e.target_id != note.note_id]
            self.graph_view.load_graph(self.notes, self.edges)
            self.save_data(silent=True)

    def _delete_prereqs_dialog(self, note: NoteNode):
        """Open dialog to selectively remove prerequisite edges attached to a note."""
        attached = [e for e in self.edges if e.source_id == note.note_id or e.target_id == note.note_id]
        if not attached:
            QMessageBox.information(self, "No Prerequisites", f"Note '{note.title}' has no attached prerequisite connections.")
            return

        notes_map = {n.note_id: n for n in self.notes}
        dialog = DeletePrereqsDialog(note, self.edges, notes_map, self)
        if dialog.exec():
            edges_to_remove = set(dialog.selected_edges_to_delete)
            self.current_course.edges = [e for e in self.edges if e not in edges_to_remove]
            self.graph_view.load_graph(self.notes, self.edges)
            self.save_data(silent=True)
            QMessageBox.information(self, "Prerequisites Removed", f"✓ Removed {len(edges_to_remove)} prerequisite connection(s).")

    def _on_snap_toggled(self, checked: bool):
        """Toggle Snapping Mode on Explorer canvas, coloring button green when active."""
        self.graph_view.set_snapping_enabled(checked)
        if checked:
            self.btn_snap_toggle.setText("🧲 Snapping ON")
            self.btn_snap_toggle.setStyleSheet("background-color: #10b981; color: white; padding: 6px 10px; font-weight: bold; border-radius: 6px;")
        else:
            self.btn_snap_toggle.setText("🧲 Snapping Off")
            self.btn_snap_toggle.setStyleSheet("background-color: #1e293b; color: #94a3b8; padding: 6px 10px; font-weight: bold; border-radius: 6px;")


    def _on_prereq_edge_created(self, source_id: str, target_id: str):
        """Handler for interactive prerequisite drawing mode."""
        # Check if edge already exists
        if any(e.source_id == source_id and e.target_id == target_id for e in self.edges):
            return
        new_edge = NoteEdge(source_id, target_id, "Prerequisite")
        self.edges.append(new_edge)
        self.graph_view.load_graph(self.notes, self.edges)
        self.save_data(silent=True)

    def _auto_arrange_graph(self):
        self.graph_view.auto_arrange()

    def save_data(self, silent: bool = False):
        """Save active course to Courses/ and scheduling/ directories."""
        if self.current_course:
            course_storage.save_course(self.current_course)
            if not silent:
                QMessageBox.information(
                    self, 
                    "Course Saved", 
                    f"Saved '{self.current_course.name}' to:\n• Courses/{self.current_course.name}.json\n• scheduling/{self.current_course.name}_scheduling.json"
                )

    def closeEvent(self, event):
        """Auto-save active course state losslessly on window close."""
        if self.current_course:
            self.save_data(silent=True)
        event.accept()


from styles import apply_global_dark_theme, DARK_THEME_QSS

if __name__ == "__main__":
    if sys.platform == 'win32':
        myappid = 'morphism.srs.proofapp.1.0'
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            pass

    app = QApplication(sys.argv)
    apply_global_dark_theme(app)
    icon_file = "icon.png" if os.path.exists("icon.png") else ("icon.ico" if os.path.exists("icon.ico") else None)
    if icon_file:
        app.setWindowIcon(QIcon(icon_file))

    window = MainWindow()
    window.show()
    sys.exit(app.exec())

