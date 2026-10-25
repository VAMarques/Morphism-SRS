from __future__ import annotations

from datetime import datetime, timedelta, timezone
from http import HTTPStatus
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from morphism_srs.controllers.event_bus import EventBus
from morphism_srs.controllers.review_controller import ReviewController
from morphism_srs.domain.enums import CardState, NoteReviewMode
from morphism_srs.domain.models import CardModel, CourseModel, NoteModel
from morphism_srs.domain.scheduler_engine import SchedulerEngine
from morphism_srs.services.dsl_compiler.compiler import DSLCompiler
from morphism_srs.services.mobile_server import EphemeralMobileServer
from morphism_srs.services.safe_html import sanitize_math_html
from morphism_srs.storage.database import DatabaseManager
from morphism_srs.storage.media_vault import MediaVault
from morphism_srs.storage.repositories.browser_repo import BrowserRepository
from morphism_srs.storage.repositories.card_repo import CardRepository
from morphism_srs.storage.repositories.course_repo import CourseRepository
from morphism_srs.storage.repositories.note_repo import NoteRepository


class TestRemergeV2Features(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name)
        self.db_path = self.root / "test_v2.sqlite3"
        self.schema_path = SRC_DIR / "morphism_srs" / "storage" / "schema_v2.sql"
        self.tags_csv = SRC_DIR / "morphism_srs" / "resources" / "defaults" / "tags_default.csv"
        self.db_mgr = DatabaseManager(self.db_path, self.schema_path, self.tags_csv)
        self.db_mgr.initialize()
        self.conn = self.db_mgr.connection

        self.course_repo = CourseRepository(self.conn)
        self.note_repo = NoteRepository(self.conn)
        self.card_repo = CardRepository(self.conn)
        self.browser_repo = BrowserRepository(self.conn)
        self.vault = MediaVault(self.conn, self.root / "media")

    def tearDown(self) -> None:
        self.conn.close()
        self.db_mgr.close()
        try:
            self.tmp_dir.cleanup()
        except Exception:
            pass

    def test_math_lt_gt_sanitization(self) -> None:
        r"""Math < and > must only be converted to \lt and \gt inside math delimiters, not outside."""
        raw = "Text with <div class='math'>$x < y$ and $a > b$ and $$c < d$$ and \\(e > f\\) and 1 < 2 outside</div>"
        sanitized = sanitize_math_html(raw)

        # Inside math
        self.assertIn(r"$x \lt  y$", sanitized)
        self.assertIn(r"$a \gt  b$", sanitized)
        self.assertIn(r"$$c \lt  d$$", sanitized)
        self.assertIn(r"\(e \gt  f\)", sanitized)

        # Outside math: HTML tags and normal text outside $...$ are strictly preserved
        self.assertIn("<div class='math'>", sanitized)
        self.assertIn("</div>", sanitized)
        self.assertIn("1 < 2 outside", sanitized)

    def test_fsrs_engine_retention_and_learning_steps(self) -> None:
        """FSRS v5 engine must default to 0.80 retention and 10-minute learning/relearning steps."""
        engine = SchedulerEngine()
        self.assertEqual(engine.desired_retention, 0.80)
        self.assertEqual(engine.scheduler.learning_steps, (timedelta(minutes=10),))
        self.assertEqual(engine.scheduler.relearning_steps, (timedelta(minutes=10),))

    def test_decoupled_note_course_and_soft_delete(self) -> None:
        """Notes can belong to courses via course_notes; unlinking must soft-delete without removing note."""
        c1 = self.course_repo.create(CourseModel(name="Course 1", desired_retention=0.80))
        c2 = self.course_repo.create(CourseModel(name="Course 2", desired_retention=0.80))

        n1 = self.note_repo.create(
            NoteModel(
                course_id=c1.id,
                title="Shared Note",
                premise_html="Standard note",
                review_mode=NoteReviewMode.STANDARD,
                cards=[CardModel(step_order=0, front_html="Q", back_html="A")],
            )
        )
        assert n1.id is not None
        assert c1.id is not None
        assert c2.id is not None

        # Link to c2 as well (many-to-many injection)
        self.note_repo.inject_into_course(c2.id, n1.id, pos_x=120, pos_y=150)

        c1_notes = self.note_repo.list_by_course(c1.id)
        c2_notes = self.note_repo.list_by_course(c2.id)
        self.assertEqual(len(c1_notes), 1)
        self.assertEqual(len(c2_notes), 1)
        self.assertEqual(c1_notes[0].id, n1.id)
        self.assertEqual(c2_notes[0].id, n1.id)

        # Soft-delete (unlink from Course 1)
        self.note_repo.unlink_from_course(c1.id, n1.id)

        self.assertEqual(len(self.note_repo.list_by_course(c1.id)), 0)
        self.assertEqual(len(self.note_repo.list_by_course(c2.id)), 1)
        # Note still exists in DB
        fetched = self.note_repo.get_by_id(n1.id)
        self.assertIsNotNone(fetched)

    def test_browser_note_and_card_queries(self) -> None:
        """BrowserRepository queries notes and cards correctly (with LEFT JOIN so missing schedules are included)."""
        c = self.course_repo.create(CourseModel(name="Algebra", desired_retention=0.80))
        assert c.id is not None

        n = self.note_repo.create(
            NoteModel(
                course_id=c.id,
                title="Vector Spaces",
                premise_html="Definition",
                review_mode=NoteReviewMode.SERIAL,
                cards=[
                    CardModel(step_order=0, front_html="P1", back_html="A1"),
                    CardModel(step_order=1, front_html="P2", back_html="A2"),
                ],
                tags=["math", "linear"],
            )
        )

        # Note Browser query
        notes = self.browser_repo.search_notes(query_text="Vector")
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].title, "Vector Spaces")
        self.assertEqual(notes[0].card_count, 2)
        self.assertIn("linear", notes[0].tags_csv)

        # Card Browser query
        cards = self.browser_repo.search_cards(query_text="Vector")
        self.assertEqual(len(cards), 2)
        self.assertEqual(cards[0].note_title, "Vector Spaces")
        self.assertEqual(cards[0].step_order, 0)
        self.assertEqual(cards[1].step_order, 1)

    def test_mdsl_uuid_preservation(self) -> None:
        """Importing MDSL with UUID must update existing note and preserve card schedule histories."""
        compiler = DSLCompiler(self.conn, self.vault)
        mdsl_v1 = """@course "Test Course"

@note euler_thm
title: "Euler Theorem"
mode: serial
uuid: "note-uuid-12345"
tags: [number_theory]
---
[step 1: Statement]
Q: Statement
A: $a^{\\varphi(n)} \\equiv 1 \\pmod{n}$
[step 2: Reduced residue system]
Q: Reduced residue system
A: Multiplication by $a$ permutes residues.
---
"""
        res1 = compiler.compile_and_commit(mdsl_v1)
        self.assertFalse(res1.has_errors)
        c_id = res1.course_id
        self.assertIsNotNone(c_id)

        # Manually rate Step 1 so it has a review schedule history
        notes = self.note_repo.list_by_course(c_id)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].uuid, "note-uuid-12345")
        cards = notes[0].cards
        self.assertEqual(len(cards), 2)

        card1_id = cards[0].id
        assert card1_id is not None
        self.conn.execute(
            """
            UPDATE card_schedules
            SET reps = 5, stability = 14.2, state = 2, due_at = '2026-11-01T00:00:00Z'
            WHERE card_id = ?;
            """,
            (card1_id,),
        )
        self.conn.commit()

        # Now re-compile updated MDSL referencing the same UUID
        mdsl_v2 = """@course "Test Course"

@note euler_thm
title: "Euler-Fermat Theorem"
mode: serial
uuid: "note-uuid-12345"
tags: [number_theory, advanced]
---
[step 1: Statement revised]
Q: Statement revised
A: $a^{\\varphi(n)} \\equiv 1 \\pmod{n}$
[step 2: Permutation argument]
Q: Permutation argument
A: Residues permuted.
---
"""
        res2 = compiler.compile_and_commit(mdsl_v2, target_course_id=c_id)
        self.assertFalse(res2.has_errors)

        # Verify note was updated, not duplicated
        notes_after = self.note_repo.list_by_course(c_id)
        self.assertEqual(len(notes_after), 1)
        self.assertEqual(notes_after[0].title, "Euler-Fermat Theorem")
        self.assertEqual(notes_after[0].uuid, "note-uuid-12345")

        # Step 1 schedule MUST be preserved
        card_obj = self.card_repo.get_by_id(card1_id)
        self.assertIsNotNone(card_obj)
        sched = card_obj.schedule
        self.assertIsNotNone(sched)
        self.assertEqual(sched.reps, 5)
        self.assertEqual(sched.stability, 14.2)
        self.assertEqual(sched.state, CardState.REVIEW)

        # Decompile must emit NEW NOTE "..." UUID <uuid>
        course = self.course_repo.get_by_id(c_id)
        assert course is not None
        decompiled = compiler.decompile_course(course, notes_after, [])
        self.assertIn("UUID note-uuid-12345", decompiled)
        self.assertNotIn("CARD UUID", decompiled)

    def test_ephemeral_mobile_sync_v2_pull_and_push(self) -> None:
        """Mobile Server V2 must support /api/v2/sync/pull and /api/v2/sync/push."""
        c = self.course_repo.create(CourseModel(name="Mobile Course", desired_retention=0.80))
        assert c.id is not None
        n = self.note_repo.create(
            NoteModel(
                course_id=c.id,
                title="Mobile Sync Note",
                premise_html="Content",
                review_mode=NoteReviewMode.STANDARD,
                cards=[CardModel(step_order=0, front_html="Q", back_html="A")],
            )
        )
        assert n.id is not None
        card_id = n.cards[0].id
        assert card_id is not None

        bus = EventBus()
        rev_ctrl = ReviewController(self.conn, bus)
        server = EphemeralMobileServer(
            conn=self.conn,
            review_controller=rev_ctrl,
            media_vault=self.vault,
            event_bus=bus,
            allow_legacy=True,
        )
        server.start()
        try:
            base = f"http://127.0.0.1:{server.port}"
            tok = server.token

            # 1. Invalid token forbidden
            with self.assertRaises(HTTPError) as ctx:
                urlopen(f"{base}/api/v2/sync/pull?token=invalid_token", timeout=3)
            self.assertEqual(ctx.exception.code, HTTPStatus.FORBIDDEN)

            # 2. Pull synchronized DB
            with urlopen(f"{base}/api/v2/sync/pull?token={tok}", timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["version"], "2.2.0")
            self.assertTrue(any(course["name"] == "Mobile Course" for course in data["courses"]))
            self.assertTrue(any(note["title"] == "Mobile Sync Note" for note in data["notes"]))
            self.assertTrue(any(card["id"] == card_id for card in data["cards"]))

            # 3. Push review updates from mobile
            now_iso = datetime.now(timezone.utc).isoformat()
            push_payload = {
                "card_schedules": [
                    {
                        "card_id": card_id,
                        "state": 2,
                        "step": 0,
                        "stability": 8.5,
                        "difficulty": 4.2,
                        "due_at": "2026-11-10T00:00:00Z",
                        "last_review_at": now_iso,
                        "reps": 3,
                        "lapses": 0,
                        "scheduled_days": 8,
                        "elapsed_days": 1,
                    }
                ],
                "review_logs": [
                    {
                        "card_id": card_id,
                        "rating": 3,
                        "elapsed_days": 1,
                        "scheduled_days": 8,
                        "state_before": 0,
                        "state_after": 2,
                        "stability_after": 8.5,
                        "reviewed_at": now_iso,
                    }
                ],
            }
            req = Request(
                f"{base}/api/v2/sync/push?token={tok}",
                data=json.dumps(push_payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(req, timeout=3) as resp:
                push_resp = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(push_resp["ok"])
            self.assertEqual(push_resp["schedules_synced"], 1)
            self.assertEqual(push_resp["logs_synced"], 1)

            # Verify schedule updated in SQLite
            card_obj = self.card_repo.get_by_id(card_id)
            self.assertIsNotNone(card_obj)
            sched = card_obj.schedule
            self.assertIsNotNone(sched)
            self.assertEqual(sched.reps, 3)
            self.assertEqual(sched.stability, 8.5)
            self.assertEqual(sched.state, CardState.REVIEW)
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
