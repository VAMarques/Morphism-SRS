"""Comprehensive verification suite for Morphism SRS Prototype 2 (v0.2.0) fixes."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtWidgets import QApplication

from morphism_srs import __version__
from morphism_srs.config import AppConfig, AppPaths
from morphism_srs.controllers.event_bus import EventBus
from morphism_srs.controllers.explorer_controller import ExplorerController
from morphism_srs.controllers.review_controller import ReviewController
from morphism_srs.domain.enums import NoteReviewMode
from morphism_srs.domain.models import (
    CardModel,
    CourseModel,
    EdgeModel,
    NoteMetrics,
    NoteModel,
    ScratchbookPageModel,
)
from morphism_srs.services.dsl_compiler import DSLCompiler
from morphism_srs.services.qr_generator import encode_qr_matrix, render_qr_pixmap
from morphism_srs.storage.database import DatabaseManager
from morphism_srs.storage.media_vault import MediaVault
from morphism_srs.storage.repositories.course_repo import CourseRepository
from morphism_srs.storage.repositories.note_repo import NoteRepository
from morphism_srs.storage.repositories.scratch_repo import ScratchRepository
from morphism_srs.storage.unit_of_work import UnitOfWork
from morphism_srs.theming.theme_manager import ThemeManager
from morphism_srs.ui.dialogs.mobile_qr_dialog import MobileQRDialog
from morphism_srs.ui.dialogs.node_editor_dialog import NodeEditorDialog
from morphism_srs.ui.dialogs.scratchbook_dialog import ScratchbookDialog
from morphism_srs.ui.main_window import MainWindow
from morphism_srs.ui.views.explorer_view import GraphEdgeItem, GraphNodeItem
from morphism_srs.web_engine.scheme_handler import register_morphism_scheme
from morphism_srs.web_engine.web_profile import WebEngineProfileManager


_SCHEME_REGISTERED = False


def _get_qapp() -> QApplication:
    global _SCHEME_REGISTERED
    app = QApplication.instance()
    if app is None:
        if not _SCHEME_REGISTERED:
            register_morphism_scheme()
            _SCHEME_REGISTERED = True
        app = QApplication([])
    return app


def _make_test_env(tmp_dir: Path):
    _get_qapp()
    paths = AppPaths(custom_base_dir=tmp_dir)
    paths.ensure_dirs()
    config = AppConfig(paths)
    db = DatabaseManager(
        db_path=paths.db_path,
        schema_path=paths.schema_sql_path,
        tags_csv_path=paths.defaults_dir / "tags_default.csv",
    )
    db.initialize()
    media_vault = MediaVault(db.connection, paths.media_dir)
    theme_manager = ThemeManager(
        themes_dir=paths.themes_dir,
        styles_dir=paths.styles_dir,
        initial_theme="dark_slate",
    )
    web_profile = WebEngineProfileManager(
        web_root=paths.web_dir,
        media_vault=media_vault,
        theme_manager=theme_manager,
        config=config,
    )
    return paths, config, db, media_vault, theme_manager, web_profile


class TestV020Fixes(unittest.TestCase):
    def test_version_is_0_2_2(self):
        self.assertEqual(__version__, "0.2.2")

    def test_main_window_version_parameter(self):
        _get_qapp()
        with tempfile.TemporaryDirectory() as tmp:
            _, config, db, media_vault, theme_manager, web_profile = _make_test_env(Path(tmp))
            try:
                win = MainWindow(
                    conn=db.connection,
                    config=config,
                    media_vault=media_vault,
                    theme_manager=theme_manager,
                    web_profile=web_profile,
                    version="0.2.2-custom",
                )
                self.assertEqual(win.app_version, "0.2.2-custom")
                self.assertIn("v0.2.2-custom", win.windowTitle())
                win.close()
            finally:
                web_profile.cleanup_all_views()
                db.close()

    def test_canonical_mdsl_compiler_and_to_import_test_file(self):
        test_mdsl_path = Path(__file__).resolve().parents[1] / "to_import" / "test.mdsl"
        readme_path = Path(__file__).resolve().parents[1] / "to_import" / "README.md"
        self.assertTrue(test_mdsl_path.exists(), "to_import/test.mdsl must exist in project root")
        self.assertTrue(readme_path.exists(), "to_import/README.md must exist in project root")

        with tempfile.TemporaryDirectory() as tmp:
            _, _, db, _, _, web_profile = _make_test_env(Path(tmp))
            try:
                compiler = DSLCompiler(db.connection)
                source = test_mdsl_path.read_text(encoding="utf-8")
                result = compiler.check_only(source)
                self.assertFalse(result.has_errors, f"test.mdsl failed to validate: {[d.message for d in result.diagnostics]}")
                self.assertIsNotNone(result.ast)
                self.assertEqual(result.ast.course_name, "Group Theory & Homomorphisms")
                self.assertEqual(result.ast.folder_path, "Pure Mathematics/Algebra")
                self.assertEqual(len(result.ast.notes), 3)

                comp_res = compiler.compile_and_commit(source)
                self.assertFalse(comp_res.has_errors)
                self.assertIsNotNone(comp_res.course_id)
                self.assertEqual(comp_res.edges_created, 2)

                course = CourseRepository(db.connection).get_by_id(comp_res.course_id)
                notes = NoteRepository(db.connection).list_by_course(comp_res.course_id)
                edges = NoteRepository(db.connection).list_edges_by_course(comp_res.course_id)

                # Decompile and verify canonical format (no PREMISE or HINT)
                decompiled = compiler.decompile_course(course, notes, edges, folder_path="Pure Mathematics/Algebra")
                self.assertIn("NEW NOTE", decompiled)
                self.assertNotIn("PREMISE", decompiled)
                self.assertNotIn("HINT:", decompiled)

                reval = compiler.check_only(decompiled)
                self.assertFalse(reval.has_errors, f"Decompiled MDSL failed to validate: {[d.message for d in reval.diagnostics]}")
            finally:
                web_profile.cleanup_all_views()
                db.close()

    def test_mathjax_macros_loaded_in_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, config, db, _, _, web_profile = _make_test_env(Path(tmp))
            try:
                tex_cfg = config.load_mathjax_tex_config()
                self.assertIn("macros", tex_cfg)
                macros = tex_cfg["macros"]
                for expected in ("R", "RR", "C", "CC", "N", "NN", "Z", "ZZ", "Q", "QQ", "Hom", "Ker", "Im"):
                    self.assertIn(expected, macros)
            finally:
                web_profile.cleanup_all_views()
                db.close()

    def test_node_editor_preserves_card_1_on_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, config, db, media_vault, _, web_profile = _make_test_env(Path(tmp))
            try:
                course_repo = CourseRepository(db.connection)
                note_repo = NoteRepository(db.connection)
                with UnitOfWork(db.connection):
                    course = course_repo.create(CourseModel(name="Algebraic Topology"))
                    cid = int(course.id)
                    created_note = note_repo.create(
                        NoteModel(
                            id=None,
                            course_id=cid,
                            title="Theorem: Fundamental Group of Circle",
                            review_mode=NoteReviewMode.SERIAL,
                            cards=[
                                CardModel(
                                    id=None,
                                    note_id=None,
                                    step_order=0,
                                    title="Path Lifting Setup",
                                    front_html=r"State the path lifting property for $p: \R \to S^1$.",
                                    back_html=r"For every path $\gamma: I \to S^1$ starting at $x_0$, there is a unique lift $\tilde{\gamma}$.",
                                ),
                                CardModel(
                                    id=None,
                                    note_id=None,
                                    step_order=1,
                                    title="Monodromy Isomorphism",
                                    front_html=r"Define the degree map $\Phi: \pi_1(S^1) \to \Z$.",
                                    back_html=r"$\Phi([\gamma]) = \tilde{\gamma}(1) \in \Z$.",
                                ),
                            ],
                        )
                    )
                    nid = int(created_note.id)

                existing_note = note_repo.get_by_id(nid)
                dlg = NodeEditorDialog(
                    conn=db.connection,
                    config=config,
                    media_vault=media_vault,
                    web_profile=web_profile,
                    course_id=cid,
                    note=existing_note,
                )

                # Card 1 must NOT be wiped out when NodeEditorDialog opens!
                self.assertEqual(dlg.note.cards[0].title, "Path Lifting Setup")
                self.assertIn("path lifting property", dlg.note.cards[0].front_html)
                self.assertIn("unique lift", dlg.note.cards[0].back_html)
                self.assertEqual(dlg.card_title_edit.text(), "Path Lifting Setup")
                self.assertIn("path lifting property", dlg.front_edit.toPlainText())
                self.assertIn("unique lift", dlg.back_edit.toPlainText())

                # Switch to Card 2 and back to Card 1
                dlg.steps_list.setCurrentRow(1)
                self.assertEqual(dlg.card_title_edit.text(), "Monodromy Isomorphism")
                self.assertIn("degree map", dlg.front_edit.toPlainText())

                dlg.steps_list.setCurrentRow(0)
                self.assertEqual(dlg.card_title_edit.text(), "Path Lifting Setup")
                self.assertIn("path lifting property", dlg.front_edit.toPlainText())

                dlg.close()
            finally:
                web_profile.cleanup_all_views()
                db.close()

    def test_scratchbook_has_no_mdsl_and_cleans_legacy_sample(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, config, db, _, _, web_profile = _make_test_env(Path(tmp))
            try:
                scratch_repo = ScratchRepository(db.connection)
                with UnitOfWork(db.connection):
                    scratch_repo.create(
                        ScratchbookPageModel(
                            title="Sample .mdsl Deck",
                            content_text='COURSE "Algebraic Topology" {}',
                        )
                    )

                dlg = ScratchbookDialog(
                    conn=db.connection,
                    web_profile=web_profile,
                    config=config,
                )
                pages = scratch_repo.list_all()
                self.assertTrue(all(p.title != "Sample .mdsl Deck" for p in pages))
                dlg.close()
            finally:
                web_profile.cleanup_all_views()
                db.close()

    def test_explorer_cardinal_ports_and_force_study(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, db, _, theme_manager, web_profile = _make_test_env(Path(tmp))
            try:
                event_bus = EventBus()
                explorer_ctrl = ExplorerController(db.connection, event_bus)
                review_ctrl = ReviewController(db.connection, event_bus)
                course_repo = CourseRepository(db.connection)
                note_repo = NoteRepository(db.connection)

                with UnitOfWork(db.connection):
                    course = course_repo.create(CourseModel(name="Category Theory"))
                    cid = int(course.id)
                    parent_note_created = note_repo.create(
                        NoteModel(
                            id=None,
                            course_id=cid,
                            title="Def: Category",
                            pos_x=100.0,
                            pos_y=100.0,
                            cards=[CardModel(id=None, note_id=None, step_order=0, title="Def", front_html="Q1", back_html="A1")],
                        )
                    )
                    child_note_created = note_repo.create(
                        NoteModel(
                            id=None,
                            course_id=cid,
                            title="Def: Functor",
                            pos_x=100.0,
                            pos_y=280.0,
                            cards=[CardModel(id=None, note_id=None, step_order=0, title="Def", front_html="Q2", back_html="A2")],
                        )
                    )
                    parent_id = int(parent_note_created.id)
                    child_id = int(child_note_created.id)
                explorer_ctrl.create_edge(cid, parent_id, child_id)

                parent_note = note_repo.get_by_id(parent_id)
                child_note = note_repo.get_by_id(child_id)
                metrics = NoteMetrics(
                    note_id=parent_id,
                    card_count=1,
                    r_min=0.0,
                    r_avg=0.0,
                    p_joint=0.0,
                    due_count=1,
                    new_count=1,
                )
                n1 = GraphNodeItem(parent_note, metrics, theme_manager, explorer_view=None)
                n2 = GraphNodeItem(child_note, metrics, theme_manager, explorer_view=None)
                edge_item = GraphEdgeItem(EdgeModel(course_id=cid, source_note_id=parent_id, target_note_id=child_id), n1, n2, theme_manager)

                # Vertically aligned: tip point must land on the North cardinal port of n2 (x = 100.0, y = 280.0 - hh2)
                _, hh2 = n2.cardinal_extents()
                self.assertAlmostEqual(edge_item._tip_point.x(), 100.0, places=4)
                self.assertAlmostEqual(edge_item._tip_point.y(), 280.0 - hh2, places=4)

                # Force study on child note
                count = review_ctrl.start_note_study(child_id, force_all_cards=True)
                self.assertEqual(count, 1)
            finally:
                web_profile.cleanup_all_views()
                db.close()

    def test_qr_generator_and_dialog(self):
        _get_qapp()
        matrix = encode_qr_matrix("http://192.168.1.42:8765/?token=abcdef123456")
        self.assertGreaterEqual(len(matrix), 21)
        self.assertEqual(len(matrix), len(matrix[0]))
        pixmap = render_qr_pixmap("http://192.168.1.42:8765/?token=abcdef123456", module_px=6)
        self.assertFalse(pixmap.isNull())
        self.assertGreaterEqual(pixmap.width(), 150)

        with tempfile.TemporaryDirectory() as tmp:
            paths, _, db, media_vault, _, web_profile = _make_test_env(Path(tmp))
            try:
                event_bus = EventBus()
                review_ctrl = ReviewController(db.connection, event_bus)
                dlg = MobileQRDialog(
                    conn=db.connection,
                    review_controller=review_ctrl,
                    media_vault=media_vault,
                    web_root=paths.web_dir,
                    event_bus=event_bus,
                )
                dlg.close()
            finally:
                web_profile.cleanup_all_views()
                db.close()

    def test_sync_live_appdata_config_and_clean_legacy_scratchbook(self):
        """Ensure user's live AppData has updated mathjax_macros.json and no Sample .mdsl Deck."""
        live_paths = AppPaths.resolve()
        default_macros_src = live_paths.defaults_dir / "mathjax_macros.json"
        target_macros = live_paths.config_dir / "mathjax_macros.json"
        if default_macros_src.exists():
            target_macros.write_text(
                default_macros_src.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        if live_paths.db_path.exists():
            db = DatabaseManager(
                db_path=live_paths.db_path,
                schema_path=live_paths.schema_sql_path,
                tags_csv_path=live_paths.defaults_dir / "tags_default.csv",
            )
            db.initialize()
            try:
                with UnitOfWork(db.connection):
                    db.connection.execute(
                        "DELETE FROM scratchbook_pages WHERE title = ?",
                        ("Sample .mdsl Deck",),
                    )
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
