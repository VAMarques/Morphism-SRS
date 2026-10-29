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

    def test_card_uuid_recognition_in_mdsl(self) -> None:
        """Compiler must recognize cards by their unique UUID, not by name or index alone."""
        compiler = DSLCompiler(self.conn)
        mdsl = """COURSE "Card UUID Test"
NEW NOTE "Basis Theorem" UUID basis-note-uuid
MODE standard

CARD 1 "Dimension Definition" UUID card-uuid-111
FRONT
What is dimension?
BACK
Cardinality of a basis.

CARD 2 "Spanning Set" UUID card-uuid-222
FRONT
What is a spanning set?
BACK
A set whose linear span is the space.
"""
        res1 = compiler.compile_and_commit(mdsl)
        self.assertFalse(res1.has_errors)
        c_id = res1.course_id
        assert c_id is not None

        notes = self.note_repo.list_by_course(c_id)
        self.assertEqual(len(notes), 1)
        cards = notes[0].cards
        self.assertEqual(len(cards), 2)
        card_111 = next(c for c in cards if c.uuid == "card-uuid-111")
        card_222 = next(c for c in cards if c.uuid == "card-uuid-222")

        # Set distinct schedule for card 111
        self.conn.execute("UPDATE card_schedules SET reps = 10, stability = 45.0 WHERE card_id = ?", (card_111.id,))
        self.conn.commit()

        # Recompile with swapped order and renamed titles, but preserving UUIDs
        mdsl_v2 = """COURSE "Card UUID Test"
NEW NOTE "Basis Theorem" UUID basis-note-uuid
MODE standard

CARD 1 "Renamed Spanning" UUID card-uuid-222
FRONT
Updated spanning question
BACK
Updated spanning answer

CARD 2 "Renamed Dimension" UUID card-uuid-111
FRONT
Updated dimension question
BACK
Updated dimension answer
"""
        res2 = compiler.compile_and_commit(mdsl_v2, target_course_id=c_id)
        self.assertFalse(res2.has_errors)

        notes_after = self.note_repo.list_by_course(c_id)
        cards_after = notes_after[0].cards
        self.assertEqual(len(cards_after), 2)

        card_111_after = next(c for c in cards_after if c.uuid == "card-uuid-111")
        card_222_after = next(c for c in cards_after if c.uuid == "card-uuid-222")

        # Step order was updated to 1 (0-based) for 111, and 0 for 222
        self.assertEqual(card_111_after.step_order, 1)
        self.assertEqual(card_222_after.step_order, 0)
        self.assertEqual(card_111_after.title, "Renamed Dimension")
        self.assertEqual(card_222_after.title, "Renamed Spanning")

        # The schedule history on 111 MUST remain preserved because it was matched by UUID!
        sched_111 = self.card_repo.get_by_id(card_111.id or 0).schedule
        assert sched_111 is not None
        self.assertEqual(sched_111.reps, 10)
        self.assertEqual(sched_111.stability, 45.0)

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


    def test_hide_answer_toggle_and_review_ui_cleanup(self) -> None:
        """Verify ReviewView key handling for backtick/0xC0 and absence of Custom/Auto buttons in header."""
        import sys
        from unittest.mock import MagicMock
        from PySide6.QtWidgets import QApplication, QPushButton
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtCore import QEvent, Qt
        _app = QApplication.instance() or QApplication(sys.argv)

        from morphism_srs.controllers.event_bus import EventBus
        from morphism_srs.controllers.review_controller import ReviewController
        from morphism_srs.ui.views.review_view import ReviewView

        event_bus = EventBus()
        from PySide6.QtWidgets import QWidget
        from PySide6.QtCore import Signal
        class MockWebView(QWidget):
            def __init__(self, parent=None):
                super().__init__(parent)
                self.loadFinished = MagicMock()
                self.setUrl = MagicMock()
                self._page = MagicMock()
            def page(self):
                return self._page

        media_vault = self.vault
        web_profile = MagicMock()
        web_profile.create_web_view.side_effect = lambda parent: MockWebView(parent)
        rev_ctrl = ReviewController(self.conn, event_bus)

        # Seed a course with a card
        import uuid
        c_id = self.conn.execute("INSERT INTO courses(uuid, name) VALUES (?, 'Test Review')", (str(uuid.uuid4()),)).lastrowid
        n_id = self.conn.execute("INSERT INTO notes(uuid, title, premise_html, review_mode) VALUES (?, 'TNote', 'P', 'standard')", (str(uuid.uuid4()),)).lastrowid
        self.conn.execute("INSERT INTO course_notes(course_id, note_id) VALUES (?, ?)", (c_id, n_id))
        c1_id = self.conn.execute("INSERT INTO cards(uuid, note_id, step_order, title, front_html, back_html) VALUES (?, ?, 0, 'C1', 'F1', 'B1')", (str(uuid.uuid4()), n_id)).lastrowid
        self.conn.execute("UPDATE card_schedules SET state = 0, due_at = '2020-01-01T00:00:00Z' WHERE card_id = ?", (c1_id,))
        self.conn.commit()

        view = ReviewView(self.conn, MagicMock(), media_vault, web_profile, rev_ctrl, event_bus)

        # 1. Verify header does not contain Custom Study or Auto-Study buttons
        header_texts = [btn.text() for btn in view.findChildren(QPushButton)]
        self.assertNotIn("Custom Study...", header_texts)
        self.assertNotIn("Auto-Study Due", header_texts)

        # 2. Start review and test hide/reveal toggle shortcut without affecting FSRS
        rev_ctrl.start_auto_study()
        view._render_current_card()
        self.assertFalse(view._answer_shown)

        # Simulate backtick key press (0xC0 / QuoteLeft)
        ev_backtick = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_QuoteLeft, Qt.KeyboardModifier.NoModifier, "`")
        view.keyPressEvent(ev_backtick)
        self.assertTrue(view._answer_shown)
        self.assertFalse(view._answer_temp_hidden)

        # Pressing again hides the answer (temp hidden) without submitting any rating
        view.keyPressEvent(ev_backtick)
        self.assertTrue(view._answer_temp_hidden)

        # Verify card schedule was completely unaffected (reps still 0, state still 0)
        sched_row = self.conn.execute("SELECT reps, state FROM card_schedules WHERE card_id = ?", (c1_id,)).fetchone()
        self.assertEqual(sched_row[0], 0)
        self.assertEqual(sched_row[1], 0)

        # Pressing again unhides it
        view.keyPressEvent(ev_backtick)
        self.assertFalse(view._answer_temp_hidden)


    def test_note_browser_course_filtering_and_na_group(self) -> None:
        """Verify Note Browser course filtering in both Cards and Notes modes, including N/A (unassigned)."""
        import uuid
        from morphism_srs.controllers.event_bus import EventBus
        from morphism_srs.storage.repositories.browser_repo import BrowserRepository
        from morphism_srs.controllers.browser_controller import BrowserController

        b_repo = BrowserRepository(self.conn)
        b_ctrl = BrowserController(self.conn, EventBus())

        # Create Course 1
        c1_id = self.conn.execute("INSERT INTO courses(uuid, name) VALUES (?, 'Analysis I')", (str(uuid.uuid4()),)).lastrowid
        # Create Course 2
        c2_id = self.conn.execute("INSERT INTO courses(uuid, name) VALUES (?, 'Algebra I')", (str(uuid.uuid4()),)).lastrowid

        # Note 1: in Course 1
        n1_id = self.conn.execute(
            "INSERT INTO notes(uuid, title, premise_html, review_mode, course_id) VALUES (?, 'Analysis Note 1', 'P1', 'standard', ?)",
            (str(uuid.uuid4()), c1_id),
        ).lastrowid
        self.conn.execute("INSERT INTO course_notes(course_id, note_id) VALUES (?, ?)", (c1_id, n1_id))
        self.conn.execute(
            "INSERT INTO cards(uuid, note_id, step_order, title, front_html, back_html) VALUES (?, ?, 0, 'Card N1', 'F', 'B')",
            (str(uuid.uuid4()), n1_id),
        )

        # Note 2: in Course 2
        n2_id = self.conn.execute(
            "INSERT INTO notes(uuid, title, premise_html, review_mode, course_id) VALUES (?, 'Algebra Note 1', 'P2', 'standard', ?)",
            (str(uuid.uuid4()), c2_id),
        ).lastrowid
        self.conn.execute("INSERT INTO course_notes(course_id, note_id) VALUES (?, ?)", (c2_id, n2_id))
        self.conn.execute(
            "INSERT INTO cards(uuid, note_id, step_order, title, front_html, back_html) VALUES (?, ?, 0, 'Card N2', 'F', 'B')",
            (str(uuid.uuid4()), n2_id),
        )

        # Note 3: Unassigned (N/A) -> course_id is NULL, not in course_notes
        n3_id = self.conn.execute(
            "INSERT INTO notes(uuid, title, premise_html, review_mode, course_id) VALUES (?, 'Unassigned Note', 'P3', 'standard', NULL)",
            (str(uuid.uuid4()),),
        ).lastrowid
        self.conn.execute(
            "INSERT INTO cards(uuid, note_id, step_order, title, front_html, back_html) VALUES (?, ?, 0, 'Card Unassigned', 'F', 'B')",
            (str(uuid.uuid4()), n3_id),
        )
        self.conn.commit()

        # Test search_notes:
        # 1. Without course filter -> returns all 3 notes
        all_notes = b_ctrl.search_notes("")
        all_titles = {n.title for n in all_notes}
        self.assertIn("Analysis Note 1", all_titles)
        self.assertIn("Algebra Note 1", all_titles)
        self.assertIn("Unassigned Note", all_titles)

        # 2. Filter by Course 1 -> only Analysis Note 1
        c1_notes = b_ctrl.search_notes("", course_id=c1_id)
        self.assertEqual([n.title for n in c1_notes], ["Analysis Note 1"])
        self.assertEqual(c1_notes[0].course_name, "Analysis I")

        # 3. Filter by Course 2 -> only Algebra Note 1
        c2_notes = b_ctrl.search_notes("", course_id=c2_id)
        self.assertEqual([n.title for n in c2_notes], ["Algebra Note 1"])
        self.assertEqual(c2_notes[0].course_name, "Algebra I")

        # 4. Filter by N/A (course_id = -1) -> only Unassigned Note
        na_notes = b_ctrl.search_notes("", course_id=-1)
        self.assertEqual([n.title for n in na_notes], ["Unassigned Note"])
        self.assertEqual(na_notes[0].course_name, "N/A")

        # Test search_cards:
        # 5. Filter cards by Course 1
        c1_cards = b_ctrl.search_cards("", course_id=c1_id)
        self.assertEqual([c.card_title for c in c1_cards], ["Card N1"])

        # 6. Filter cards by N/A (course_id = -1)
        na_cards = b_ctrl.search_cards("", course_id=-1)
        self.assertEqual([c.card_title for c in na_cards], ["Card Unassigned"])
        self.assertEqual(na_cards[0].course_name, "N/A")


    def test_course_view_moving_and_note_table_headers(self) -> None:
        """Verify moving courses into folders, folders into folders/root, and NoteBrowserTableModel headers."""
        import sys
        from unittest.mock import MagicMock
        from PySide6.QtWidgets import QApplication
        _app = QApplication.instance() or QApplication(sys.argv)

        from morphism_srs.controllers.event_bus import EventBus
        from morphism_srs.controllers.review_controller import ReviewController
        from morphism_srs.domain.models import CourseFolderModel, CourseModel
        from morphism_srs.ui.views.browser_view import NoteBrowserTableModel
        from morphism_srs.ui.views.courses_view import CoursesView

        # 1. Verify NoteBrowserTableModel HEADERS do NOT include Course
        table_model = NoteBrowserTableModel()
        self.assertNotIn("Course", table_model.HEADERS)
        self.assertEqual(table_model.HEADERS, ["Note Title", "Mode", "Cards", "Tags", "UUID", "Created"])

        # 2. Test CoursesView moving logic
        event_bus = EventBus()
        rev_ctrl = ReviewController(self.conn, event_bus)
        courses_view = CoursesView(self.conn, self.vault, rev_ctrl, event_bus)

        # Create folder F1 and F2
        f1 = courses_view.folder_repo.create(CourseFolderModel(name="Math"))
        f2 = courses_view.folder_repo.create(CourseFolderModel(name="Algebra", parent_id=f1.id))
        c1 = self.course_repo.create(CourseModel(name="Linear Algebra", folder_id=None))

        # Initial state: c1 is at root
        c1_db = self.course_repo.get_by_id(c1.id)
        self.assertIsNone(c1_db.folder_id)

        # Move c1 into f2
        courses_view._on_item_moved("course", c1.id, f2.id)
        c1_db = self.course_repo.get_by_id(c1.id)
        self.assertEqual(c1_db.folder_id, f2.id)

        # Move c1 back to root (None)
        courses_view._on_item_moved("course", c1.id, None)
        c1_db = self.course_repo.get_by_id(c1.id)
        self.assertIsNone(c1_db.folder_id)

        # Move f2 to root
        courses_view._on_item_moved("folder", f2.id, None)
        f2_db = courses_view.folder_repo.get_by_id(f2.id)
        self.assertIsNone(f2_db.parent_id)

        # Move f2 back into f1
        courses_view._on_item_moved("folder", f2.id, f1.id)
        f2_db = courses_view.folder_repo.get_by_id(f2.id)
        self.assertEqual(f2_db.parent_id, f1.id)

if __name__ == "__main__":
    unittest.main()
