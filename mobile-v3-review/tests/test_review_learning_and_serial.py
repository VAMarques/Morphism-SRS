from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from morphism_srs.controllers.event_bus import EventBus
from morphism_srs.controllers.review_controller import CustomStudyConfig, ReviewController
from morphism_srs.domain.enums import CardState, NoteReviewMode, RatingEnum
from morphism_srs.domain.models import CardModel, CardScheduleModel, CourseModel, NoteModel
from morphism_srs.domain.scheduler_engine import SchedulerEngine, parse_utc
from morphism_srs.storage.database import DatabaseManager
from morphism_srs.storage.repositories.course_repo import CourseRepository
from morphism_srs.storage.repositories.note_repo import NoteRepository


class TestReviewLearningAndSerial(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name)
        self.db_path = self.root / "test_review.sqlite3"
        self.schema_path = SRC_DIR / "morphism_srs" / "storage" / "schema_v2.sql"
        self.tags_csv = SRC_DIR / "morphism_srs" / "resources" / "defaults" / "tags_default.csv"
        self.db_mgr = DatabaseManager(self.db_path, self.schema_path, self.tags_csv)
        self.db_mgr.initialize()
        self.conn = self.db_mgr.connection
        self.event_bus = EventBus()
        self.controller = ReviewController(self.conn, self.event_bus)
        self.note_repo = NoteRepository(self.conn)
        self.course_repo = CourseRepository(self.conn)

        course = self.course_repo.create(CourseModel(name="Analysis"))
        self.course_id = course.id

    def tearDown(self) -> None:
        self.db_mgr.close()
        self.tmp_dir.cleanup()

    def test_scheduler_10m_steps_learning_and_relearning(self) -> None:
        engine = SchedulerEngine()
        now = datetime.now(timezone.utc)

        # 1. New card rated Again has ~10m interval and state LEARNING
        new_sched = CardScheduleModel(card_id=1, state=CardState.NEW)
        sched_again, log1 = engine.rate_card(new_sched, RatingEnum.AGAIN, now=now)
        self.assertEqual(sched_again.state, CardState.LEARNING)
        self.assertEqual(sched_again.step, 0)
        due_delta = parse_utc(sched_again.due_at) - now
        self.assertAlmostEqual(due_delta.total_seconds(), 600.0, delta=5.0)

        # 2. Rating Good on learning card graduates to REVIEW
        sched_good, log2 = engine.rate_card(sched_again, RatingEnum.GOOD, now=now)
        self.assertEqual(sched_good.state, CardState.REVIEW)
        self.assertGreaterEqual((parse_utc(sched_good.due_at) - now).total_seconds(), 86000.0)

        # 3. Review card rated Again enters RELEARNING with ~10m interval
        sched_relapse, log3 = engine.rate_card(sched_good, RatingEnum.AGAIN, now=now)
        self.assertEqual(sched_relapse.state, CardState.RELEARNING)
        self.assertEqual(sched_relapse.step, 0)
        relearn_delta = parse_utc(sched_relapse.due_at) - now
        self.assertAlmostEqual(relearn_delta.total_seconds(), 600.0, delta=5.0)

        # 4. Rating Good on relearning card graduates back to REVIEW
        sched_restored, log4 = engine.rate_card(sched_relapse, RatingEnum.GOOD, now=now)
        self.assertEqual(sched_restored.state, CardState.REVIEW)

    def test_serial_note_again_does_not_advance_to_next_step(self) -> None:
        # Create a serial proof note with 3 steps
        cards = [
            CardModel(step_order=0, title="Step 1", front_html="Proof Setup", back_html="Let eps > 0"),
            CardModel(step_order=1, title="Step 2", front_html="Delta Selection", back_html="Choose delta = eps / 2"),
            CardModel(step_order=2, title="Step 3", front_html="Conclusion", back_html="|f(x)-L| < eps QED"),
        ]
        note = self.note_repo.create(
            NoteModel(course_id=self.course_id, title="Eps-Delta Proof", review_mode=NoteReviewMode.SERIAL, cards=cards)
        )

        # Start studying the serial note
        total = self.controller.start_note_study(note.id)
        self.assertEqual(total, 3)

        # Step 1 is the active card
        ctx1 = self.controller.current_prompt_context()
        self.assertIsNotNone(ctx1)
        self.assertEqual(ctx1.card.step_order, 0)
        self.assertEqual(ctx1.card.title, "Step 1")
        self.assertEqual(len(ctx1.conditioning_siblings), 0)

        # User presses Again on Step 1: MUST NOT jump to Step 2!
        remains = self.controller.submit_rating(RatingEnum.AGAIN)
        self.assertTrue(remains)

        # Verify we are STILL on Step 1
        ctx1_retry = self.controller.current_prompt_context()
        self.assertIsNotNone(ctx1_retry)
        self.assertEqual(ctx1_retry.card.step_order, 0)
        self.assertEqual(ctx1_retry.card.title, "Step 1")
        self.assertEqual(self.controller.current_Index_1based(), 1)

        # User presses Again a second time on Step 1: STILL stays on Step 1
        self.controller.submit_rating(RatingEnum.AGAIN)
        ctx1_retry2 = self.controller.current_prompt_context()
        self.assertIsNotNone(ctx1_retry2)
        self.assertEqual(ctx1_retry2.card.step_order, 0)

        # User dominates Step 1 and rates Good: NOW it advances to Step 2!
        remains = self.controller.submit_rating(RatingEnum.GOOD)
        self.assertTrue(remains)

        ctx2 = self.controller.current_prompt_context()
        self.assertIsNotNone(ctx2)
        self.assertEqual(ctx2.card.step_order, 1)
        self.assertEqual(ctx2.card.title, "Step 2")
        # Step 1 is in conditioning_siblings before Step 2
        self.assertEqual(len(ctx2.conditioning_siblings), 1)
        self.assertEqual(ctx2.conditioning_siblings[0].step_order, 0)
        self.assertEqual(ctx2.conditioning_siblings[0].position, "before")

        # In Step 2, user presses Again: MUST NOT jump to Step 3!
        self.controller.submit_rating(RatingEnum.AGAIN)
        ctx2_retry = self.controller.current_prompt_context()
        self.assertIsNotNone(ctx2_retry)
        self.assertEqual(ctx2_retry.card.step_order, 1)
        self.assertEqual(ctx2_retry.card.title, "Step 2")

        # Now dominate Step 2 with Good -> advances to Step 3
        self.controller.submit_rating(RatingEnum.GOOD)
        ctx3 = self.controller.current_prompt_context()
        self.assertIsNotNone(ctx3)
        self.assertEqual(ctx3.card.step_order, 2)
        self.assertEqual(ctx3.card.title, "Step 3")
        self.assertEqual(len(ctx3.conditioning_siblings), 2)

        # Rate Good on Step 3 -> note completes, no more cards!
        self.controller.submit_rating(RatingEnum.GOOD)
        ctx_done = self.controller.current_prompt_context()
        self.assertIsNone(ctx_done)

    def test_serial_hard_advances_and_cycles_back_to_earliest_step(self) -> None:
        """
        In a serial note:
        - Hard MUST advance to the next step.
        - Upon reaching the end of the stack, it must cycle back to the earliest unmastered step (Step 1 if necessary),
          without showing any steps i > 1 in past steps.
        """
        cards = [
            CardModel(step_order=0, title="Step 1", front_html="Q1", back_html="A1"),
            CardModel(step_order=1, title="Step 2", front_html="Q2", back_html="A2"),
            CardModel(step_order=2, title="Step 3", front_html="Q3", back_html="A3"),
        ]
        note = self.note_repo.create(
            NoteModel(course_id=self.course_id, title="Serial Proof", review_mode=NoteReviewMode.SERIAL, cards=cards)
        )
        self.controller.start_note_study(note.id)

        # Step 1 is active: user rates Hard -> MUST advance to Step 2!
        ctx1 = self.controller.current_prompt_context()
        self.assertEqual(ctx1.card.step_order, 0)
        self.controller.submit_rating(RatingEnum.HARD)

        # Now at Step 2!
        ctx2 = self.controller.current_prompt_context()
        self.assertIsNotNone(ctx2)
        self.assertEqual(ctx2.card.step_order, 1)
        self.assertEqual(len(ctx2.conditioning_siblings), 1)
        self.assertEqual(ctx2.conditioning_siblings[0].step_order, 0)

        # Rate Good on Step 2 -> advances to Step 3!
        self.controller.submit_rating(RatingEnum.GOOD)
        ctx3 = self.controller.current_prompt_context()
        self.assertIsNotNone(ctx3)
        self.assertEqual(ctx3.card.step_order, 2)

        # Rate Good on Step 3 -> final step of stack passed!
        self.controller.submit_rating(RatingEnum.GOOD)

        # Stack ended, but Step 1 was rated Hard!
        # MUST cycle back to Step 1 (the earliest unmastered step)!
        ctx_cycle = self.controller.current_prompt_context()
        self.assertIsNotNone(ctx_cycle)
        self.assertEqual(ctx_cycle.card.step_order, 0)
        self.assertEqual(ctx_cycle.card.title, "Step 1")

        # Crucial check: Step 1 MUST NOT have any steps i > 1 in conditioning_siblings!
        self.assertEqual(len(ctx_cycle.conditioning_siblings), 0)

        # Now master Step 1 with Good -> stack is now fully mastered!
        self.controller.submit_rating(RatingEnum.GOOD)
        self.assertIsNone(self.controller.current_prompt_context())

    def test_serial_hard_on_step2_cycles_to_step2_not_step1(self) -> None:
        """
        When Step 1 was Good and Step 2 was Hard, cycling back goes to Step 2 (the earliest unmastered step),
        with Step 1 visible in past steps, but NOT Step 3 (no steps i > 2).
        """
        cards = [
            CardModel(step_order=0, title="Step 1", front_html="Q1", back_html="A1"),
            CardModel(step_order=1, title="Step 2", front_html="Q2", back_html="A2"),
            CardModel(step_order=2, title="Step 3", front_html="Q3", back_html="A3"),
        ]
        note = self.note_repo.create(
            NoteModel(course_id=self.course_id, title="Serial Proof 2", review_mode=NoteReviewMode.SERIAL, cards=cards)
        )
        self.controller.start_note_study(note.id)

        # Step 1: Good -> advances to Step 2
        self.controller.submit_rating(RatingEnum.GOOD)
        self.assertEqual(self.controller.current_prompt_context().card.step_order, 1)

        # Step 2: Hard -> advances to Step 3
        self.controller.submit_rating(RatingEnum.HARD)
        self.assertEqual(self.controller.current_prompt_context().card.step_order, 2)

        # Step 3: Good -> stack ends
        self.controller.submit_rating(RatingEnum.GOOD)

        # Cycles back to Step 2 (NOT Step 1!)
        ctx_cycle = self.controller.current_prompt_context()
        self.assertIsNotNone(ctx_cycle)
        self.assertEqual(ctx_cycle.card.step_order, 1)
        self.assertEqual(ctx_cycle.card.title, "Step 2")

        # Step 1 is in past steps, but Step 3 (i > 2) is NOT!
        self.assertEqual(len(ctx_cycle.conditioning_siblings), 1)
        self.assertEqual(ctx_cycle.conditioning_siblings[0].step_order, 0)

        # Master Step 2 with Good -> note complete
        self.controller.submit_rating(RatingEnum.GOOD)
        self.assertIsNone(self.controller.current_prompt_context())

    def test_serial_hard_on_step1_and_step2_cycles_both_in_order(self) -> None:
        cards = [
            CardModel(step_order=0, title="Step 1", front_html="Q1", back_html="A1"),
            CardModel(step_order=1, title="Step 2", front_html="Q2", back_html="A2"),
            CardModel(step_order=2, title="Step 3", front_html="Q3", back_html="A3"),
        ]
        note = self.note_repo.create(
            NoteModel(course_id=self.course_id, title="Serial Proof 3", review_mode=NoteReviewMode.SERIAL, cards=cards)
        )
        self.controller.start_note_study(note.id)

        # Step 1: Hard -> advances to Step 2
        self.controller.submit_rating(RatingEnum.HARD)
        # Step 2: Hard -> advances to Step 3
        self.controller.submit_rating(RatingEnum.HARD)
        # Step 3: Good -> stack ends
        self.controller.submit_rating(RatingEnum.GOOD)

        # Stack ended: earliest unmastered is Step 1
        ctx_step1 = self.controller.current_prompt_context()
        self.assertIsNotNone(ctx_step1)
        self.assertEqual(ctx_step1.card.step_order, 0)
        self.assertEqual(len(ctx_step1.conditioning_siblings), 0)

        # User masters Step 1 with Good -> moves to Step 2
        self.controller.submit_rating(RatingEnum.GOOD)
        ctx_step2 = self.controller.current_prompt_context()
        self.assertIsNotNone(ctx_step2)
        self.assertEqual(ctx_step2.card.step_order, 1)
        self.assertEqual(len(ctx_step2.conditioning_siblings), 1)
        self.assertEqual(ctx_step2.conditioning_siblings[0].step_order, 0)

        # User masters Step 2 with Good -> all steps done!
        self.controller.submit_rating(RatingEnum.GOOD)
        self.assertIsNone(self.controller.current_prompt_context())

    def test_serial_sandbox_hard_advances_and_cycles(self) -> None:
        cards = [
            CardModel(step_order=0, title="Step 1", front_html="Q1", back_html="A1"),
            CardModel(step_order=1, title="Step 2", front_html="Q2", back_html="A2"),
        ]
        note = self.note_repo.create(
            NoteModel(course_id=self.course_id, title="Sandbox Proof", review_mode=NoteReviewMode.SERIAL, cards=cards)
        )
        cfg = CustomStudyConfig(note_ids=[note.id], cram_sandbox=True)
        self.controller.start_custom_study(cfg)
        self.assertTrue(self.controller.is_cram_sandbox)

        # Active card is Step 1: rating Again stays on Step 1
        self.assertEqual(self.controller.current_prompt_context().card.step_order, 0)
        self.controller.submit_rating(RatingEnum.AGAIN)
        self.assertEqual(self.controller.current_prompt_context().card.step_order, 0)

        # Rating Hard on Step 1: advances to Step 2
        self.controller.submit_rating(RatingEnum.HARD)
        self.assertEqual(self.controller.current_prompt_context().card.step_order, 1)

        # Rating Good on Step 2: stack ends, cycles back to Step 1
        self.controller.submit_rating(RatingEnum.GOOD)
        ctx_cycle = self.controller.current_prompt_context()
        self.assertIsNotNone(ctx_cycle)
        self.assertEqual(ctx_cycle.card.step_order, 0)

        # Rating Good on Step 1: finishes sandbox session
        self.controller.submit_rating(RatingEnum.GOOD)
        self.assertIsNone(self.controller.current_prompt_context())

    def test_standard_note_requeues_until_learning_steps_finished(self) -> None:
        cards = [
            CardModel(step_order=0, title="Def 1", front_html="Q1", back_html="A1"),
            CardModel(step_order=1, title="Def 2", front_html="Q2", back_html="A2"),
        ]
        note = self.note_repo.create(
            NoteModel(course_id=self.course_id, title="Topology Defs", review_mode=NoteReviewMode.STANDARD, cards=cards)
        )

        total = self.controller.start_note_study(note.id)
        self.assertEqual(total, 2)

        # Card 1 is rated Again (enters learning, 10m step)
        ctx1 = self.controller.current_prompt_context()
        self.assertIsNotNone(ctx1)
        self.assertEqual(ctx1.card.title, "Def 1")
        self.controller.submit_rating(RatingEnum.AGAIN)

        # Card 2 is shown, rated Good (graduates to Review)
        ctx2 = self.controller.current_prompt_context()
        self.assertIsNotNone(ctx2)
        self.assertEqual(ctx2.card.title, "Def 2")
        self.controller.submit_rating(RatingEnum.GOOD)

        # Note MUST NOT finish because Card 1 is still in LEARNING!
        # Card 1 must be presented again:
        ctx1_retry = self.controller.current_prompt_context()
        self.assertIsNotNone(ctx1_retry)
        self.assertEqual(ctx1_retry.card.title, "Def 1")

        # User rates Card 1 Again AGAIN: Card 1 must be presented once more!
        self.controller.submit_rating(RatingEnum.AGAIN)
        ctx1_retry2 = self.controller.current_prompt_context()
        self.assertIsNotNone(ctx1_retry2)
        self.assertEqual(ctx1_retry2.card.title, "Def 1")

        # User rates Card 1 Good -> graduates!
        self.controller.submit_rating(RatingEnum.GOOD)

        # Now all cards are graduated, session is complete!
        self.assertIsNone(self.controller.current_prompt_context())

    def test_single_card_note_requeues_until_learning_graduated(self) -> None:
        cards = [
            CardModel(step_order=0, title="Single Card", front_html="Q", back_html="A"),
        ]
        note = self.note_repo.create(
            NoteModel(course_id=self.course_id, title="Single", review_mode=NoteReviewMode.STANDARD, cards=cards)
        )
        self.controller.start_note_study(note.id)

        # Rate Again
        self.controller.submit_rating(RatingEnum.AGAIN)

        # Prompt must STILL be the single card
        ctx = self.controller.current_prompt_context()
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx.card.title, "Single Card")

        # Rate Good -> graduates and queue ends
        self.controller.submit_rating(RatingEnum.GOOD)
        self.assertIsNone(self.controller.current_prompt_context())

    def test_serial_undo_rating(self) -> None:
        cards = [
            CardModel(step_order=0, title="Step 1", front_html="Q1", back_html="A1"),
            CardModel(step_order=1, title="Step 2", front_html="Q2", back_html="A2"),
        ]
        note = self.note_repo.create(
            NoteModel(course_id=self.course_id, title="Proof", review_mode=NoteReviewMode.SERIAL, cards=cards)
        )

        self.controller.start_note_study(note.id)
        # Rate Again on Step 1
        self.controller.submit_rating(RatingEnum.AGAIN)
        self.assertEqual(self.controller.current_prompt_context().card.step_order, 0)

        # Undo
        msg = self.controller.undo_last_review()
        self.assertIsNotNone(msg)
        self.assertEqual(self.controller.current_prompt_context().card.step_order, 0)

        # Rate Good on Step 1 -> advances to Step 2
        self.controller.submit_rating(RatingEnum.GOOD)
        self.assertEqual(self.controller.current_prompt_context().card.step_order, 1)

        # Undo Good on Step 1 -> returns to Step 1
        self.controller.undo_last_review()
        self.assertEqual(self.controller.current_prompt_context().card.step_order, 0)


if __name__ == "__main__":
    unittest.main()
