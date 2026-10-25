from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from pathlib import Path
import sys
import unittest

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from morphism_srs.domain.enums import CardState, NoteReviewMode, RatingEnum
from morphism_srs.domain.models import CardModel, CardScheduleModel, NoteModel
from morphism_srs.domain.scheduler_engine import SchedulerEngine


class TestSchedulerAndConditioning(unittest.TestCase):
    def test_note_metrics_r_min_r_avg_p_joint(self) -> None:
        now = datetime.now(timezone.utc)
        s1 = CardScheduleModel(
            card_id=1,
            state=CardState.REVIEW,
            stability=10.0,
            difficulty=5.0,
            due_at=(now + timedelta(days=5)).isoformat(),
            last_review_at=(now - timedelta(days=5)).isoformat(),
        )
        s2 = CardScheduleModel(
            card_id=2,
            state=CardState.REVIEW,
            stability=2.0,
            difficulty=7.0,
            due_at=(now - timedelta(days=1)).isoformat(),
            last_review_at=(now - timedelta(days=5)).isoformat(),
        )
        r1 = SchedulerEngine.compute_card_retrievability(s1, now)
        r2 = SchedulerEngine.compute_card_retrievability(s2, now)
        metrics = SchedulerEngine.compute_note_metrics(10, [s1, s2], now)

        self.assertAlmostEqual(metrics.r_min, min(r1, r2), places=6)
        self.assertAlmostEqual(metrics.r_avg, (r1 + r2) / 2.0, places=6)
        self.assertAlmostEqual(metrics.p_joint, r1 * r2, places=6)
        self.assertTrue(metrics.p_joint < metrics.r_min)

    def test_serial_vs_cloze_conditioning(self) -> None:
        engine = SchedulerEngine(desired_retention=0.90)
        cards = [
            CardModel(id=101, step_order=0, title="Step 1", front_html="Q1", back_html="A1"),
            CardModel(id=102, step_order=1, title="Step 2", front_html="Q2", back_html="A2"),
            CardModel(id=103, step_order=2, title="Step 3", front_html="Q3", back_html="A3"),
        ]

        # Serial: P(A_2 | A_1) -> only j < i (Step 1) is given
        serial_note = NoteModel(id=1, title="Serial Proof", review_mode=NoteReviewMode.SERIAL, cards=cards)
        ctx_serial = engine.build_prompt_context(cards[1], serial_note, "Algebra")
        self.assertEqual(len(ctx_serial.conditioning_siblings), 1)
        self.assertEqual(ctx_serial.conditioning_siblings[0].card_id, 101)
        self.assertEqual(ctx_serial.conditioning_siblings[0].position, "before")

        # Cloze: P(A_2 | A_1, A_3) -> all j != i (Step 1 before AND Step 3 after) are given
        cloze_note = NoteModel(id=2, title="Equivalent Characterizations", review_mode=NoteReviewMode.CLOZE, cards=cards)
        ctx_cloze = engine.build_prompt_context(cards[1], cloze_note, "Topology")
        self.assertEqual(len(ctx_cloze.conditioning_siblings), 2)
        self.assertEqual(ctx_cloze.conditioning_siblings[0].card_id, 101)
        self.assertEqual(ctx_cloze.conditioning_siblings[0].position, "before")
        self.assertEqual(ctx_cloze.conditioning_siblings[1].card_id, 103)
        self.assertEqual(ctx_cloze.conditioning_siblings[1].position, "after")

    def test_kahns_topological_sort(self) -> None:
        notes = [1, 2, 3, 4]
        edges = [(1, 2), (2, 3), (1, 4), (4, 3)]
        ordered = SchedulerEngine.topological_sort_notes(notes, edges)
        self.assertEqual(ordered[0], 1)
        self.assertEqual(ordered[-1], 3)


if __name__ == "__main__":
    unittest.main()
