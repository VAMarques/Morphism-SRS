from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtWidgets import QApplication

from morphism_srs.config import AppConfig, AppPaths
from morphism_srs.controllers.event_bus import EventBus
from morphism_srs.controllers.explorer_controller import ExplorerController
from morphism_srs.domain.models import (
    CardModel,
    CourseModel,
    EdgeModel,
    NoteModel,
)
from morphism_srs.storage.media_vault import MediaVault
from morphism_srs.storage.database import DatabaseManager
from morphism_srs.storage.unit_of_work import UnitOfWork
from morphism_srs.ui.dialogs.delete_prereqs_dialog import DeleteNoteDialog


class TestBulkAndInPlaceLayout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.paths = AppPaths(custom_base_dir=self.root)
        self.paths.ensure_dirs()
        self.config = AppConfig(self.paths)

        self.db = DatabaseManager(
            db_path=self.paths.db_path,
            schema_path=self.paths.schema_sql_path,
            tags_csv_path=self.paths.defaults_dir / "tags_default.csv",
        )
        self.db.initialize()
        self.conn = self.db.connection
        self.event_bus = EventBus()
        self.controller = ExplorerController(self.conn, self.event_bus)

        # Create course
        with UnitOfWork(self.conn):
            self.course = self.controller.course_repo.create(CourseModel(name="Math Course"))
            assert self.course.id is not None
            self.cid = self.course.id

            # Create 3 notes far from origin
            self.n1 = self.controller.note_repo.create(
                NoteModel(course_id=self.cid, title="Node 1", pos_x=1000.0, pos_y=1000.0)
            )
            self.n2 = self.controller.note_repo.create(
                NoteModel(course_id=self.cid, title="Node 2", pos_x=1200.0, pos_y=1000.0)
            )
            self.n3 = self.controller.note_repo.create(
                NoteModel(course_id=self.cid, title="Node 3", pos_x=1100.0, pos_y=1300.0)
            )
            self.controller.note_repo.create_edge(
                EdgeModel(course_id=self.cid, source_note_id=self.n1.id, target_note_id=self.n2.id)
            )
            self.controller.note_repo.create_edge(
                EdgeModel(course_id=self.cid, source_note_id=self.n2.id, target_note_id=self.n3.id)
            )

    def tearDown(self):
        if self.db is not None:
            self.db.close()
            self.db = None
            self.conn = None
        try:
            self.tmp.cleanup()
        except Exception:
            pass

    def test_inplace_auto_layout_preserves_centroid(self):
        """Auto-layout on a subset of notes must position the layout in-place near original centroid, not (0,0)."""
        subset = [self.n1.id, self.n2.id, self.n3.id]
        orig_notes = [self.controller.note_repo.get_by_id(nid) for nid in subset]
        orig_cx = sum(n.pos_x for n in orig_notes) / len(orig_notes)
        orig_cy = sum(n.pos_y for n in orig_notes) / len(orig_notes)

        self.assertAlmostEqual(orig_cx, 1100.0)
        self.assertAlmostEqual(orig_cy, 1100.0)

        # Execute in-place auto-layout on selection
        self.controller.auto_layout_course(self.cid, note_ids_subset=subset)

        new_notes = [self.controller.note_repo.get_by_id(nid) for nid in subset]
        new_cx = sum(n.pos_x for n in new_notes) / len(new_notes)
        new_cy = sum(n.pos_y for n in new_notes) / len(new_notes)

        # Centroid should remain close to (1100, 1100), within grid snap tolerance (<= 25 px)
        self.assertLess(abs(new_cx - orig_cx), 25.0)
        self.assertLess(abs(new_cy - orig_cy), 25.0)

        # Ensure they did NOT jump to near origin (0, 0)
        for n in new_notes:
            self.assertGreater(n.pos_x, 800.0)
            self.assertGreater(n.pos_y, 800.0)

    def test_bulk_suspend_and_unsuspend(self):
        """Suspending and unsuspending in bulk toggles card suspension flag."""
        with UnitOfWork(self.conn):
            c1 = self.controller.card_repo.create(CardModel(note_id=self.n1.id, step_order=0, front_html="Q1", back_html="A1"))
            c2 = self.controller.card_repo.create(CardModel(note_id=self.n2.id, step_order=0, front_html="Q2", back_html="A2"))

        # Suspend both notes
        self.controller.bulk_suspend_notes(self.cid, [self.n1.id, self.n2.id], suspended=True)
        c1_loaded = self.controller.card_repo.get_by_id(c1.id)
        c2_loaded = self.controller.card_repo.get_by_id(c2.id)
        self.assertTrue(c1_loaded.schedule.is_suspended)
        self.assertTrue(c2_loaded.schedule.is_suspended)

        # Unsuspend both notes
        self.controller.bulk_suspend_notes(self.cid, [self.n1.id, self.n2.id], suspended=False)
        c1_loaded = self.controller.card_repo.get_by_id(c1.id)
        c2_loaded = self.controller.card_repo.get_by_id(c2.id)
        self.assertFalse(c1_loaded.schedule.is_suspended)
        self.assertFalse(c2_loaded.schedule.is_suspended)

    def test_delete_note_dialog_no_html_tags(self):
        """DeleteNoteDialog radio buttons must not contain raw HTML tags."""
        dlg = DeleteNoteDialog(note_count=3)
        self.assertNotIn("<b>", dlg.unlink_rb.text())
        self.assertNotIn("<br>", dlg.unlink_rb.text())
        self.assertNotIn("<span", dlg.unlink_rb.text())
        self.assertNotIn("<b>", dlg.hard_del_rb.text())
        self.assertNotIn("<br>", dlg.hard_del_rb.text())
        self.assertNotIn("<span", dlg.hard_del_rb.text())
        self.assertTrue(dlg.is_unlink_only)
        self.assertTrue(dlg.bridge_edges)
        dlg.close()


if __name__ == "__main__":
    unittest.main()
