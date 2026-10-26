from __future__ import annotations

from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from morphism_srs.domain.enums import CardState, NoteReviewMode, RatingEnum
from morphism_srs.domain.models import CourseFolderModel, CourseModel, NoteModel
from morphism_srs.storage.database import DatabaseManager
from morphism_srs.storage.media_vault import MediaVault
from morphism_srs.storage.repositories.browser_repo import BrowserRepository
from morphism_srs.storage.repositories.course_repo import CourseRepository
from morphism_srs.storage.repositories.folder_repo import FolderRepository
from morphism_srs.storage.repositories.note_repo import NoteRepository
from morphism_srs.storage.repositories.review_repo import ReviewRepository


class TestDatabaseAndRepositories(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name)
        self.db_path = self.root / "test_v2.sqlite3"
        self.schema_path = SRC_DIR / "morphism_srs" / "storage" / "schema_v2.sql"
        self.tags_csv = SRC_DIR / "morphism_srs" / "resources" / "defaults" / "tags_default.csv"
        self.db_mgr = DatabaseManager(self.db_path, self.schema_path, self.tags_csv)
        self.db_mgr.initialize()
        self.conn = self.db_mgr.connection

    def tearDown(self) -> None:
        self.db_mgr.close()
        self.tmp_dir.cleanup()

    def test_tags_seeded_2000(self) -> None:
        row = self.conn.execute("SELECT COUNT(*) AS cnt FROM tags;").fetchone()
        self.assertEqual(int(row["cnt"]), 2000)

    def test_folder_cycle_prevention_trigger(self) -> None:
        f_repo = FolderRepository(self.conn)
        f1 = f_repo.create(CourseFolderModel(name="Algebra"))
        f2 = f_repo.create(CourseFolderModel(name="Group Theory", parent_id=f1.id))
        f1.parent_id = f2.id
        with self.assertRaises(sqlite3.IntegrityError):
            f_repo.update(f1)

    def test_card_auto_schedule_and_undo_rollback(self) -> None:
        c_repo = CourseRepository(self.conn)
        n_repo = NoteRepository(self.conn)
        r_repo = ReviewRepository(self.conn)

        course = c_repo.create(CourseModel(name="Topology"))
        from morphism_srs.domain.models import CardModel
        note = n_repo.create(
            NoteModel(
                course_id=course.id or 0,
                title="Compactness",
                review_mode=NoteReviewMode.STANDARD,
                tags=["general_topology", "theorem"],
                cards=[CardModel(front_html="Define compactness", back_html="Every open cover has a finite subcover")],
            )
        )
        loaded_note = n_repo.get_by_id(note.id or 0)
        self.assertIsNotNone(loaded_note)
        assert loaded_note is not None
        self.assertEqual(len(loaded_note.cards), 1)
        card = loaded_note.cards[0]
        self.assertIsNotNone(card.schedule)
        assert card.schedule is not None
        self.assertEqual(card.schedule.state, CardState.NEW)

        from morphism_srs.domain.scheduler_engine import SchedulerEngine
        engine = SchedulerEngine(desired_retention=0.90)
        new_sched, log = engine.rate_card(card.schedule, RatingEnum.GOOD)
        saved_log = r_repo.record_review(new_sched, log)
        self.assertIsNotNone(saved_log.id)

        # Undo via Ctrl+Z rollback
        restored = r_repo.undo_review(saved_log.id or 0)
        self.assertIsNotNone(restored)
        assert restored is not None
        self.assertEqual(restored.state, CardState.NEW)
        self.assertIsNone(restored.last_review_at)
        self.assertEqual(restored.reps, 0)

    def test_fts5_search_and_media_vault(self) -> None:
        c_repo = CourseRepository(self.conn)
        n_repo = NoteRepository(self.conn)
        b_repo = BrowserRepository(self.conn)

        course = c_repo.create(CourseModel(name="Category Theory"))
        from morphism_srs.domain.models import CardModel
        n_repo.create(
            NoteModel(
                course_id=course.id or 0,
                title="Yoneda Lemma",
                review_mode=NoteReviewMode.SERIAL,
                tags=["category_theory", "yoneda_lemma"],
                cards=[CardModel(front_html="Natural isomorphism $\\text{Hom}(h^A, F) \\cong F(A)$", back_html="Proof via identity morphism")],
            )
        )

        hits = b_repo.search_cards(query_text="Yoneda tag:category_theory mode:serial")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].note_title, "Yoneda Lemma")

        vault = MediaVault(self.conn, self.root / "media")
        svg_bytes = b'<svg xmlns="http://www.w3.org/2000/svg"><circle r="10"/></svg>'
        h1, fname1 = vault.store_bytes(svg_bytes, "comm_diag.svg")
        h2, fname2 = vault.store_bytes(svg_bytes, "duplicate_name.svg")
        self.assertEqual(h1, h2)
        self.assertEqual(fname1, fname2)
        self.assertTrue(fname1.endswith(".svg"))


if __name__ == "__main__":
    unittest.main()
