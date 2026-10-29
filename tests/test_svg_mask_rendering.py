from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from morphism_srs.services.dsl_compiler.compiler import DSLCompiler
from morphism_srs.storage.database import DatabaseManager
from morphism_srs.storage.media_vault import MediaVault


class TestSvgMaskRendering(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp_dir.name)
        self.db_path = self.tmp / "test.db"
        self.media_dir = self.tmp / "media"

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
        self.vault = MediaVault(self.conn, self.media_dir)

    def tearDown(self) -> None:
        self.conn.close()
        self.temp_dir.cleanup()

    def test_cards_css_contains_svg_mask_rules(self) -> None:
        css_file = (
            Path(__file__).resolve().parent.parent
            / "src"
            / "morphism_srs"
            / "resources"
            / "web"
            / "css"
            / "cards.css"
        )
        self.assertTrue(css_file.exists(), "cards.css must exist")
        css_content = css_file.read_text(encoding="utf-8")

        self.assertIn(".diagram-mask-container", css_content)
        self.assertIn(".commutative-diagram-mask", css_content)
        self.assertIn("-webkit-mask-size", css_content)
        self.assertIn("mask-size", css_content)
        self.assertIn("background-color", css_content)

    def test_media_vault_stores_svg(self) -> None:
        svg_content = b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><circle cx="50" cy="50" r="40"/></svg>'
        sha, stored_name = self.vault.store_bytes(svg_content, "circle.svg")

        self.assertTrue(stored_name.endswith(".svg"))
        disk_path = self.vault.resolve_path(stored_name)
        self.assertIsNotNone(disk_path)
        self.assertTrue(disk_path.exists())
        self.assertEqual(disk_path.read_bytes(), svg_content)

    def test_compile_svg_mask_test_deck(self) -> None:
        deck_path = (
            Path(__file__).resolve().parent.parent
            / "to_import"
            / "svg_mask_test_deck.mdsl"
        )
        self.assertTrue(deck_path.exists(), "Sample test deck must exist")
        source = deck_path.read_text(encoding="utf-8")

        compiler = DSLCompiler(self.conn, media_vault=self.vault)
        result = compiler.compile_and_commit(
            source=source,
            source_dir=deck_path.parent,
            media_vault=self.vault,
        )

        self.assertFalse(result.has_errors, f"Compilation errors: {result.diagnostics}")
        self.assertIsNotNone(result.course_id)
        self.assertEqual(result.notes_created, 1)

        # Verify parsed AST
        self.assertEqual(result.ast.course_name, "Pruebas de Renderizado Vectorial")
        self.assertEqual(result.ast.course_uuid, "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d")
        self.assertEqual(result.ast.folder_path, "Categorías/Diagramas")

        # Verify generated card front_html has mask markup
        row = self.conn.execute("SELECT front_html FROM cards LIMIT 1;").fetchone()
        self.assertIsNotNone(row)
        front_html = row["front_html"]
        self.assertIn("diagram-mask-container", front_html)
        self.assertIn("commutative-diagram-mask", front_html)
        self.assertIn("morphism://media/", front_html)


if __name__ == "__main__":
    unittest.main()
