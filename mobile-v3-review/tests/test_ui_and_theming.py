from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from PySide6.QtWidgets import QApplication

from morphism_srs.config import AppConfig, AppPaths
from morphism_srs.domain.enums import NoteReviewMode
from morphism_srs.domain.models import CardModel, CourseModel, NoteModel
from morphism_srs.storage.database import DatabaseManager
from morphism_srs.storage.media_vault import MediaVault
from morphism_srs.storage.repositories.course_repo import CourseRepository
from morphism_srs.storage.repositories.note_repo import NoteRepository
from morphism_srs.theming.theme_manager import ThemeManager
from morphism_srs.ui.views.explorer_view import GraphNodeItem
from morphism_srs.ui.window_sizing import apply_relative_geometry
from morphism_srs.web_engine.scheme_handler import register_morphism_scheme


class TestThemingAndUIShapes(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        register_morphism_scheme()
        cls.app = QApplication.instance() or QApplication([])

    def test_theme_manager_compiles_all_3_themes_without_unresolved_tokens(self) -> None:
        paths = AppPaths.resolve()
        tm = ThemeManager(paths.themes_dir, paths.styles_dir)
        themes = dict(tm.available_themes())
        self.assertIn("dark_slate", themes)
        self.assertIn("light_paper", themes)
        self.assertIn("oled_midnight", themes)

        for tid in ("dark_slate", "light_paper", "oled_midnight"):
            tm.apply_theme(tid)
            qss = tm.compile_qss()
            self.assertNotIn("{{", qss)
            self.assertNotIn("}}", qss)
            css_js = tm.compile_css_variables_js()
            self.assertIn("--bg-primary", css_js)

    def test_no_inline_setstylesheet_outside_theme_manager(self) -> None:
        ui_dir = SRC_DIR / "morphism_srs" / "ui"
        for py_file in ui_dir.rglob("*.py"):
            content = py_file.read_text(encoding="utf-8")
            self.assertNotIn(".setStyleSheet(", content, f"Inline setStyleSheet found in {py_file}")

    def test_explorer_node_shapes_rectangle_diamond_ellipse(self) -> None:
        from morphism_srs.domain.models import NoteMetrics
        paths = AppPaths.resolve()
        tm = ThemeManager(paths.themes_dir, paths.styles_dir)
        dummy_metrics = NoteMetrics(1, 1, 0.9, 0.9, 0.9, 0, 0)

        n_std = NoteModel(id=1, title="Std", review_mode=NoteReviewMode.STANDARD)
        n_ser = NoteModel(id=2, title="Ser", review_mode=NoteReviewMode.SERIAL)
        n_clz = NoteModel(id=3, title="Clz", review_mode=NoteReviewMode.CLOZE)

        item_std = GraphNodeItem(n_std, dummy_metrics, tm, None)  # type: ignore[arg-type]
        item_ser = GraphNodeItem(n_ser, dummy_metrics, tm, None)  # type: ignore[arg-type]
        item_clz = GraphNodeItem(n_clz, dummy_metrics, tm, None)  # type: ignore[arg-type]

        # Diamond corner (80, 34) is inside RoundedRect but outside Rhombus/Diamond
        from PySide6.QtCore import QPointF
        corner_pt = QPointF(80.0, 32.0)
        self.assertTrue(item_std.shape().contains(corner_pt))
        self.assertFalse(item_ser.shape().contains(corner_pt))
        self.assertFalse(item_clz.shape().contains(corner_pt))


if __name__ == "__main__":
    unittest.main()
