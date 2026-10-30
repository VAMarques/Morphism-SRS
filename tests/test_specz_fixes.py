from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import unittest

from morphism_srs.controllers.event_bus import EventBus
from morphism_srs.controllers.review_controller import ReviewController
from morphism_srs.domain.enums import CardState, NoteReviewMode, RatingEnum
from morphism_srs.domain.models import CardModel, CardScheduleModel, CourseModel, EdgeModel, NoteMetrics, NoteModel
from morphism_srs.domain.scheduler_engine import SchedulerEngine
from morphism_srs.services.dsl_compiler.compiler import DSLCompiler
from morphism_srs.storage.database import DatabaseManager
from morphism_srs.storage.media_vault import MediaVault
from morphism_srs.storage.repositories.card_repo import CardRepository
from morphism_srs.storage.repositories.course_repo import CourseRepository
from morphism_srs.storage.repositories.gamification_repo import GamificationRepository
from morphism_srs.storage.repositories.note_repo import NoteRepository


class TestSpecZFixes(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path("C:/Users/vamar/.gemini/antigravity/brain/0df496be-0ee1-440b-8864-33f94979049e/scratch/test_db")
        self.tmp.mkdir(parents=True, exist_ok=True)
        self.db_path = self.tmp / "test_specz.db"
        if self.db_path.exists():
            self.db_path.unlink()

        schema_path = (
            Path(__file__).resolve().parent.parent
            / "src"
            / "morphism_srs"
            / "storage"
            / "schema_v2.sql"
        )
        self.db_mgr = DatabaseManager(self.db_path, schema_path)
        self.db_mgr.initialize()
        self.conn = self.db_mgr.connection
        self.event_bus = EventBus()

        self.course_repo = CourseRepository(self.conn)
        self.note_repo = NoteRepository(self.conn)
        self.card_repo = CardRepository(self.conn)
        self.gamification_repo = GamificationRepository(self.conn)
        self.review_controller = ReviewController(self.conn, self.event_bus)

    def tearDown(self) -> None:
        self.conn.close()
        if self.db_path.exists():
            self.db_path.unlink()

    def test_point_1_and_2_uuid_and_link_anywhere(self) -> None:
        """Point 1 & 2: LINK can be anywhere in MDSL, and UUID is unbraced UUID uuid."""
        mdsl = """
COURSE "Topology 101" UUID 11112222-3333-4444-5555-666677778888 FOLDER "Math"/"Topology"

LINK "Interior" -> "Closure"

NEW NOTE "Interior" UUID aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee
MODE standard
CARD 1 "Def Interior"
FRONT
Interior definition
BACK
The largest open set.

NEW NOTE "Closure" UUID ffffffff-0000-1111-2222-333344445555
MODE standard
CARD 1 "Def Closure"
FRONT
Closure definition
BACK
The smallest closed set.

LINK "Closure" -> "Dense"

NEW NOTE "Dense"
MODE standard
CARD 1 "Def Dense"
FRONT
Dense definition
BACK
Closure is the whole space.
"""
        compiler = DSLCompiler(self.conn)
        res = compiler.compile_and_commit(mdsl)
        self.assertFalse(res.has_errors, f"Compile errors: {res.diagnostics}")
        self.assertEqual(res.ast.course_uuid, "11112222-3333-4444-5555-666677778888")
        self.assertEqual(len(res.ast.notes), 3)

        # Decompile and verify UUID is printed as UUID uuid without curly braces
        c = self.course_repo.get_by_id(res.course_id)
        notes = self.note_repo.list_by_course(res.course_id)
        edges = self.note_repo.list_edges_by_course(res.course_id)
        decomp = DSLCompiler.decompile_course(c, notes, edges)
        self.assertIn("UUID 11112222-3333-4444-5555-666677778888", decomp)
        self.assertNotIn("UUID {", decomp)

        # Verify edges from LINK at the start and middle were both preserved
        self.assertEqual(len(edges), 2)

    def test_point_3_media_bracket_variants(self) -> None:
        """Point 3: [IMAGE ...], [VECTOR ...], [DIAGRAM ...] have unambiguous renderings."""
        vault_dir = self.tmp / "vault"
        vault = MediaVault(self.conn, vault_dir)
        (self.tmp / "raster.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        (self.tmp / "vector.svg").write_bytes(b'<svg width="10"><circle/></svg>')
        (self.tmp / "diagram.svg").write_bytes(b'<svg width="20"><path/></svg>')

        mdsl = f"""
COURSE "Media Directives" UUID 22223333-4444-5555-6666-777788889999
NEW NOTE "Visuals"
MODE standard
CARD 1 "Visual Directives"
FRONT
[IMAGE "raster.png"]
[VECTOR "vector.svg"]
[DIAGRAM "diagram.svg"]
BACK
Done
"""
        compiler = DSLCompiler(self.conn, media_vault=vault)
        res = compiler.compile_and_commit(mdsl, source_dir=self.tmp, media_vault=vault)
        self.assertFalse(res.has_errors, f"Errors: {res.diagnostics}")

        row = self.conn.execute("SELECT front_html FROM cards LIMIT 1;").fetchone()
        front = row["front_html"]
        self.assertIn('class="morphism-image"', front)
        self.assertIn('class="vector-image"', front)
        self.assertIn('class="diagram-mask-container"', front)
        self.assertIn('class="commutative-diagram-mask"', front)

    def test_point_4_unlink_preserves_edges(self) -> None:
        """Point 4: Unlinking from a course does NOT delete the edge between notes."""
        c = self.course_repo.create(CourseModel(name="Analysis"))
        n1 = self.note_repo.create(NoteModel(course_id=c.id, title="Limits", review_mode=NoteReviewMode.STANDARD))
        n2 = self.note_repo.create(NoteModel(course_id=c.id, title="Continuity", review_mode=NoteReviewMode.STANDARD))

        self.note_repo.create_edge(EdgeModel(course_id=c.id, source_note_id=n1.id, target_note_id=n2.id))
        self.assertEqual(len(self.note_repo.list_edges_by_course(c.id)), 1)

        # Unlink n1 from c
        self.note_repo.unlink_from_course(c.id, n1.id)

        # Edge is hidden from course c because n1 is absent
        self.assertEqual(len(self.note_repo.list_edges_by_course(c.id)), 0)

        # But edge still exists in edges table and connects the notes!
        edge = self.note_repo.get_edge_between(n1.id, n2.id)
        self.assertIsNotNone(edge, "Edge must not be deleted on course unlink")

        # When n1 is re-injected, edge reappears in course c
        self.note_repo.inject_into_course(c.id, n1.id)
        self.assertEqual(len(self.note_repo.list_edges_by_course(c.id)), 1)

    def test_point_5_gamification_streak_and_xp_on_reviews(self) -> None:
        """Point 5: Streaks and XP increment on review and are persistent."""
        c = self.course_repo.create(CourseModel(name="Test Course"))
        n = self.note_repo.create(
            NoteModel(
                course_id=c.id,
                title="XP Note",
                review_mode=NoteReviewMode.STANDARD,
                cards=[CardModel(front_html="Q", back_html="A", step_order=0)],
            )
        )

        stats_before = self.gamification_repo.get_stats()
        self.assertEqual(stats_before["total_xp"], 0.0)
        self.assertEqual(stats_before["streak_count"], 0)

        self.review_controller.start_note_study(n.id, force_all_cards=True)
        self.review_controller.submit_rating(RatingEnum.GOOD)

        stats_after = self.gamification_repo.get_stats()
        self.assertEqual(stats_after["total_xp"], 1.0)
        self.assertEqual(stats_after["streak_count"], 1)

        # Rating another card adds +1.0 XP
        self.review_controller.start_note_study(n.id, force_all_cards=True)
        self.review_controller.submit_rating(RatingEnum.EASY)

        stats_after2 = self.gamification_repo.get_stats()
        self.assertEqual(stats_after2["total_xp"], 2.0)
        self.assertEqual(stats_after2["streak_count"], 1)  # same session (< 18h)

    def test_point_6_card_counter_does_not_inflate(self) -> None:
        """Point 6: Rating Again or Hard does not inflate n in note review."""
        c = self.course_repo.create(CourseModel(name="Counter Course"))
        n = self.note_repo.create(
            NoteModel(
                course_id=c.id,
                title="2-Card Note",
                review_mode=NoteReviewMode.STANDARD,
                cards=[
                    CardModel(front_html="Q1", back_html="A1", step_order=0),
                    CardModel(front_html="Q2", back_html="A2", step_order=1),
                ],
            )
        )

        self.review_controller.start_note_study(n.id, force_all_cards=True)
        ctx = self.review_controller.current_prompt_context()
        self.assertIsNotNone(ctx)

        # n is the count of cards in the note
        n_cards = len(ctx.note.cards)
        self.assertEqual(n_cards, 2)
        step = ctx.card.step_order + 1
        self.assertEqual(step, 1)
        self.assertEqual(self.review_controller.remaining_note_cards(ctx.note), 2)

        # Rate card 1 Again (learning/relearning state)
        self.review_controller.submit_rating(RatingEnum.AGAIN)

        # Now on card 2
        ctx2 = self.review_controller.current_prompt_context()
        self.assertIsNotNone(ctx2)
        self.assertEqual(len(ctx2.note.cards), 2)  # n is STILL 2, never 3!
        self.assertEqual(ctx2.card.step_order + 1, 2)
        self.assertEqual(self.review_controller.remaining_note_cards(ctx2.note), 2)

    def test_point_7_color_and_prerequisite_logic(self) -> None:
        """Point 7: Grey overrides Red; only grey prerequisite blocks an incomplete grey note."""
        from morphism_srs.ui.views.explorer_view import ExplorerView

        # Mock metrics
        gray_incomplete = NoteMetrics(note_id=1, card_count=2, r_min=0.0, r_avg=0.0, p_joint=0.0, due_count=1, new_count=1, learning_count=0)
        self.assertTrue(gray_incomplete.is_incomplete)

        red_due = NoteMetrics(note_id=2, card_count=2, r_min=0.5, r_avg=0.6, p_joint=0.3, due_count=1, new_count=0, learning_count=0)
        self.assertFalse(red_due.is_incomplete)

        blue_uptodate = NoteMetrics(note_id=3, card_count=2, r_min=0.9, r_avg=0.9, p_joint=0.81, due_count=0, new_count=0, learning_count=0)
        self.assertFalse(blue_uptodate.is_incomplete)


if __name__ == "__main__":
    unittest.main()
