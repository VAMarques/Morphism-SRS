from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from morphism_srs.controllers.event_bus import EventBus
from morphism_srs.controllers.review_controller import ReviewController
from morphism_srs.domain.models import CardModel, CourseModel, NoteModel
from morphism_srs.domain.scheduler_engine import SchedulerEngine
from morphism_srs.services.delta_sync import TABLE_KEYS, pull_delta, push_delta
from morphism_srs.services.mobile_server import EphemeralMobileServer
from morphism_srs.storage.database import DatabaseManager
from morphism_srs.storage.media_vault import MediaVault
from morphism_srs.storage.repositories.card_repo import CardRepository
from morphism_srs.storage.repositories.course_repo import CourseRepository
from morphism_srs.storage.repositories.note_repo import NoteRepository
from morphism_srs.storage.repositories.review_repo import ReviewRepository


class TestDeltaSync(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.manager = DatabaseManager(self.root / "pc.sqlite3", ROOT / "src/morphism_srs/storage/schema_v2.sql")
        self.manager.initialize()
        self.conn = self.manager.connection
        self.course = CourseRepository(self.conn).create(CourseModel(name="Algebra"))
        self.note = NoteRepository(self.conn).create(NoteModel(course_id=self.course.id, title="Lemma",
            cards=[CardModel(front_html="$a$", back_html="$b$")]))
        self.card = CardRepository(self.conn).get_by_id(self.note.cards[0].id)
        self.bootstrap = pull_delta(self.conn, 0)

    def tearDown(self):
        self.manager.close()
        self.tmp.cleanup()

    def batch(self, *logs, undone=()):
        return {"db_uuid": self.bootstrap["db_uuid"], "device_id": "test-phone",
                "new_review_logs": list(logs), "undone_log_uuids": list(undone)}

    def log(self, rating=3, day=0, local_id=1):
        now = datetime(2026, 10, 1, tzinfo=timezone.utc) + timedelta(days=day)
        _, log = SchedulerEngine().rate_card(self.card.schedule, rating, now=now)
        return {**asdict(log), "card_uuid": self.card.uuid, "local_id": local_id}

    def test_bootstrap_is_complete_and_identity_is_persistent(self):
        self.assertEqual(self.bootstrap["mode"], "bootstrap")
        self.assertEqual(set(self.bootstrap["tables"]), set(TABLE_KEYS))
        self.assertEqual(self.bootstrap["db_uuid"], pull_delta(self.conn, 0)["db_uuid"])
        self.assertEqual(len(self.bootstrap["tables"]["cards"]), 1)

    def test_triggers_update_unlink_delete_and_idempotent_schema(self):
        since = self.bootstrap["current_seq"]
        self.conn.execute("UPDATE notes SET title='Changed' WHERE id=?", (self.note.id,))
        self.conn.execute("UPDATE notes SET title='Final' WHERE id=?", (self.note.id,))
        delta = pull_delta(self.conn, since)
        self.assertEqual([n["title"] for n in delta["upserts"]["notes"]], ["Final"])
        self.assertFalse(any(delta["deletes"].values()))
        self.conn.execute("DELETE FROM course_notes WHERE course_id=?", (self.course.id,))
        delta = pull_delta(self.conn, delta["current_seq"])
        self.assertEqual(delta["deletes"]["course_notes"], [{"course_id": self.course.id, "note_id": self.note.id}])
        self.conn.execute("DELETE FROM notes WHERE id=?", (self.note.id,))
        delta = pull_delta(self.conn, delta["current_seq"])
        self.assertEqual(delta["deletes"]["cards"], [{"id": self.card.id}])
        self.assertEqual(delta["deletes"]["card_schedules"], [{"card_id": self.card.id}])
        self.manager.initialize()
        count = self.conn.execute("SELECT count(*) FROM sqlite_master WHERE name LIKE 'trg_sync_%'").fetchone()[0]
        self.assertEqual(count, 36)

    def test_every_replicated_table_has_a_trigger_and_cascade_keys(self):
        for table in TABLE_KEYS:
            for op in ("insert", "update", "delete"):
                self.assertIsNotNone(self.conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (f"trg_sync_{table}_{op}",)).fetchone())
        self.conn.execute("INSERT INTO tags(name) VALUES ('tag')")
        tag_id = self.conn.execute("SELECT id FROM tags").fetchone()[0]
        self.conn.execute("INSERT INTO note_tags VALUES (?,?)", (self.note.id, tag_id))
        since = pull_delta(self.conn, 0)["current_seq"]
        self.conn.execute("DELETE FROM tags WHERE id=?", (tag_id,))
        delta = pull_delta(self.conn, since)
        self.assertEqual(delta["deletes"]["note_tags"], [{"note_id": self.note.id, "tag_id": tag_id}])

    def test_push_retry_is_idempotent_and_returns_canonical_ids(self):
        log = self.log()
        first = push_delta(self.conn, self.batch(log))
        retry = push_delta(self.conn, self.batch(log))
        self.assertEqual(first["pushed_logs_accepted"], 1)
        self.assertEqual(retry["pushed_logs_accepted"], 0)
        self.assertEqual(first["log_ids"], retry["log_ids"])
        self.assertEqual(retry["max_local_log_id"], 1)
        card = CardRepository(self.conn).get_by_id(self.card.id)
        self.assertEqual(card.schedule.reps, 1)
        self.assertEqual(len(ReviewRepository(self.conn).list_logs_for_card(self.card.id)), 1)

    def test_concurrent_reviews_converge_independent_of_delivery_order(self):
        logs = [self.log(3, 0, 1), self.log(1, 3, 2), self.log(4, 5, 3)]
        for log in (logs[2], logs[0], logs[1]):
            push_delta(self.conn, self.batch(log))
        history = ReviewRepository(self.conn).list_logs_for_card(self.card.id)
        expected = SchedulerEngine().reschedule_from_logs(self.card.id, history)
        actual = CardRepository(self.conn).get_by_id(self.card.id).schedule
        self.assertAlmostEqual(actual.stability, expected.stability, places=12)
        self.assertAlmostEqual(actual.difficulty, expected.difficulty, places=12)
        self.assertEqual(actual.due_at, expected.due_at)
        self.assertEqual(actual.reps, 3)

    def test_undo_after_ack_or_lost_ack_wins_over_delayed_retry(self):
        log = self.log()
        push_delta(self.conn, self.batch(log))
        push_delta(self.conn, self.batch(undone=[log["uuid"]]))
        push_delta(self.conn, self.batch(log))
        actual = CardRepository(self.conn).get_by_id(self.card.id).schedule
        self.assertEqual(actual.reps, 0)
        self.assertEqual(actual.state, 0)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM review_logs").fetchone()[0], 0)

    def test_invalid_batch_rolls_back_and_wrong_database_is_rejected(self):
        good = self.log()
        bad = {**self.log(), "rating": 9}
        with self.assertRaises(ValueError):
            push_delta(self.conn, self.batch(good, bad))
        self.assertEqual(self.conn.execute("SELECT count(*) FROM review_logs").fetchone()[0], 0)
        with self.assertRaises(ValueError):
            push_delta(self.conn, {**self.batch(good), "db_uuid": "another-pc"})
        with self.assertRaises(ValueError):
            pull_delta(self.conn, self.bootstrap["current_seq"] + 999)

    def test_stale_deleted_card_review_is_acknowledged(self):
        log = self.log()
        self.conn.execute("DELETE FROM cards WHERE id=?", (self.card.id,))
        response = push_delta(self.conn, self.batch(log))
        self.assertEqual(response["max_local_log_id"], 1)
        self.assertEqual(response["pushed_logs_accepted"], 0)
        self.assertEqual(response["log_ids"], {})

    def test_imported_schedule_without_full_history_survives_push_and_undo(self):
        self.card.schedule.state = 2
        self.card.schedule.stability = 25.0
        self.card.schedule.difficulty = 4.0
        self.card.schedule.reps = 18
        self.card.schedule.lapses = 2
        self.card.schedule.last_review_at = "2026-09-01T00:00:00+00:00"
        self.card.schedule.due_at = "2026-10-15T00:00:00+00:00"
        CardRepository(self.conn).update_schedule(self.card.schedule)
        expected, log = SchedulerEngine().rate_card(self.card.schedule, 3, now=datetime(2026,10,1,tzinfo=timezone.utc))
        mobile = {**asdict(log), "card_uuid": self.card.uuid, "local_id": 1}
        push_delta(self.conn, self.batch(mobile))
        actual = CardRepository(self.conn).get_by_id(self.card.id).schedule
        self.assertAlmostEqual(actual.stability, expected.stability, places=12)
        self.assertEqual(actual.reps, 19)
        self.assertEqual(actual.lapses, 2)
        push_delta(self.conn, self.batch(undone=[log.uuid]))
        restored = CardRepository(self.conn).get_by_id(self.card.id).schedule
        self.assertEqual(restored.stability, 25.0)
        self.assertEqual(restored.reps, 18)
        self.assertEqual(restored.last_review_at, "2026-09-01T00:00:00+00:00")

    def test_http_auth_incremental_push_media_and_ui_thread_transaction(self):
        bus = EventBus()
        vault = MediaVault(self.conn, self.root / "media")
        _, name = vault.store_bytes(b'<svg xmlns="http://www.w3.org/2000/svg"/>', "test.svg")
        server = EphemeralMobileServer(self.conn, ReviewController(self.conn, bus), vault, bus, allow_legacy=True)
        server.start()
        try:
            base = f"http://127.0.0.1:{server.port}"
            with self.assertRaises(HTTPError) as error:
                urlopen(base + "/api/v2/sync/pull_delta", timeout=5)
            self.assertEqual(error.exception.code, 403)
            def get(path):
                with urlopen(base + path + ("&" if "?" in path else "?") + "token=" + server.token, timeout=5) as r:
                    return json.load(r)
            payload = get("/api/v2/sync/pull_delta?since_seq=0")
            self.assertEqual(payload["db_uuid"], self.bootstrap["db_uuid"])
            req = Request(base+"/api/v2/sync/push_delta?token="+server.token,
                          data=json.dumps(self.batch(self.log())).encode(), headers={"Content-Type":"application/json"})
            with urlopen(req, timeout=5) as r:
                self.assertEqual(json.load(r)["pushed_logs_accepted"], 1)
            self.assertTrue(get(f"/api/v2/sync/pull_delta?since_seq={payload['current_seq']}")["upserts"]["review_logs"])
            with urlopen(base+"/media/"+name+"?token="+server.token,timeout=5) as r:
                self.assertEqual(r.headers["Content-Type"], "image/svg+xml")
            # HTTP reads must not commit or roll back an active UI transaction.
            self.conn.execute("BEGIN IMMEDIATE")
            self.conn.execute("UPDATE notes SET title='Uncommitted'")
            self.assertEqual(get("/api/v2/sync/pull_delta?since_seq=0")["tables"]["notes"][0]["title"], "Lemma")
            self.assertTrue(self.conn.in_transaction)
            self.conn.execute("ROLLBACK")
        finally:
            if self.conn.in_transaction:
                self.conn.execute("ROLLBACK")
            server.stop()

    def test_portable_is_read_only_and_mathjax_waits_for_startup(self):
        mobile = ROOT / "src/morphism-portable"
        ui = (mobile / "assets/web/portable_ui.js").read_text(encoding="utf-8")
        html = (mobile / "assets/web/index.html").read_text(encoding="utf-8")
        self.assertNotIn("localStorage", ui)
        self.assertNotIn('type="file"', html)
        self.assertEqual(html.count('class="nav-tab'), 4)
        self.assertIn("startup?.promise", ui)
        config = json.loads((ROOT / "src/morphism_srs/resources/defaults/mathjax_macros.json").read_text(encoding="utf-8"))
        self.assertIn("autoload", config["packages"]["[-]"])
        self.assertIn("boldsymbol", config["packages"]["[+]"])
        self.assertIn("bm", config["macros"])


if __name__ == "__main__":
    unittest.main()
