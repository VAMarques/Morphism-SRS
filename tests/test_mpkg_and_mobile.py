from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.request import Request, urlopen

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from morphism_srs.controllers.event_bus import EventBus
from morphism_srs.controllers.review_controller import ReviewController
from morphism_srs.domain.enums import NoteReviewMode
from morphism_srs.domain.models import CardModel, CourseModel, NoteModel
from morphism_srs.services.import_export.mpkg_service import MpkgService
from morphism_srs.services.mobile_server import EphemeralMobileServer
from morphism_srs.storage.database import DatabaseManager
from morphism_srs.storage.media_vault import MediaVault
from morphism_srs.storage.repositories.course_repo import CourseRepository
from morphism_srs.storage.repositories.note_repo import NoteRepository


class TestMpkgAndMobileServer(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name)
        self.db_mgr = DatabaseManager(
            self.root / "pkg_test.sqlite3",
            SRC_DIR / "morphism_srs" / "storage" / "schema_v2.sql",
            SRC_DIR / "morphism_srs" / "resources" / "defaults" / "tags_default.csv",
        )
        self.db_mgr.initialize()
        self.conn = self.db_mgr.connection
        self.vault = MediaVault(self.conn, self.root / "media")

    def tearDown(self) -> None:
        self.db_mgr.close()
        self.tmp_dir.cleanup()

    def test_mpkg_export_and_import_roundtrip_with_svg_media(self) -> None:
        c_repo = CourseRepository(self.conn)
        n_repo = NoteRepository(self.conn)
        mpkg = MpkgService(self.conn, self.vault)

        _, stored_svg = self.vault.store_bytes(b'<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0"/></svg>', "diag.svg")
        course = c_repo.create(CourseModel(name="Homological Algebra"))
        n_repo.create(
            NoteModel(
                course_id=course.id or 0,
                title="Snake Lemma",
                review_mode=NoteReviewMode.SERIAL,
                tags=["homological_algebra", "snake_lemma"],
                cards=[
                    CardModel(
                        step_order=0,
                        title="Connecting Homomorphism",
                        front_html=f'Construct $\\delta$:<br><img src="morphism://media/{stored_svg}">',
                        back_html="Exact sequence $\\ker a \\to \\ker b \\to \\ker c \\xrightarrow{\\delta} \\text{coker } a$.",
                    )
                ],
            )
        )

        pkg_file = self.root / "homological.mpkg"
        mpkg.export_mpkg(course.id or 0, pkg_file, include_scheduling=True)
        self.assertTrue(pkg_file.exists())

        # Import into a fresh second database
        db2_mgr = DatabaseManager(
            self.root / "dest_v2.sqlite3",
            SRC_DIR / "morphism_srs" / "storage" / "schema_v2.sql",
        )
        db2_mgr.initialize()
        vault2 = MediaVault(db2_mgr.connection, self.root / "media2")
        mpkg2 = MpkgService(db2_mgr.connection, vault2)

        imported_cid = mpkg2.import_mpkg(pkg_file, include_scheduling=True)
        notes2 = NoteRepository(db2_mgr.connection).list_by_course(imported_cid)
        self.assertEqual(len(notes2), 1)
        self.assertEqual(notes2[0].title, "Snake Lemma")
        self.assertIsNotNone(vault2.resolve_path(stored_svg))
        db2_mgr.close()

    def test_ephemeral_mobile_server_lifecycle_checkout_and_checkin(self) -> None:
        c_repo = CourseRepository(self.conn)
        n_repo = NoteRepository(self.conn)
        course = c_repo.create(CourseModel(name="Functional Analysis"))
        note = n_repo.create(
            NoteModel(
                course_id=course.id or 0,
                title="Banach-Steinhaus Theorem",
                review_mode=NoteReviewMode.STANDARD,
                cards=[CardModel(front_html="State Uniform Boundedness Principle", back_html="Pointwise bounded implies norm bounded.")],
            )
        )
        card_id = note.cards[0].id
        assert card_id is not None

        bus = EventBus()
        rev_ctrl = ReviewController(self.conn, bus)
        server = EphemeralMobileServer(
            conn=self.conn,
            review_controller=rev_ctrl,
            media_vault=self.vault,
            mathjax_js_bytes=b"// mathjax stub",
            event_bus=bus,
            allow_legacy=True,
        )
        server.start()
        try:
            base = f"http://127.0.0.1:{server.port}"
            tok = server.token

            # Check-Out Offline bundle
            with urlopen(f"{base}/api/checkout?token={tok}", timeout=5) as resp:
                bundle = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(len(bundle["cards"]), 1)
            self.assertEqual(bundle["cards"][0]["card_id"], card_id)

            # Check-In Offline review log
            req = Request(
                f"{base}/api/checkin?token={tok}",
                data=json.dumps({"logs": [{"card_id": card_id, "rating": 3}]}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(req, timeout=5) as resp:
                out = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(out["synced"], 1)
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
