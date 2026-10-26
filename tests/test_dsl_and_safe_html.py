from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from morphism_srs.services.dsl_compiler.compiler import DSLCompiler
from morphism_srs.services.safe_html import sanitize_math_html
from morphism_srs.storage.database import DatabaseManager
from morphism_srs.storage.repositories.note_repo import NoteRepository


class TestDSLCompilerAndSafeHtml(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name)
        self.db_mgr = DatabaseManager(
            self.root / "dsl_test.sqlite3",
            SRC_DIR / "morphism_srs" / "storage" / "schema_v2.sql",
            SRC_DIR / "morphism_srs" / "resources" / "defaults" / "tags_default.csv",
        )
        self.db_mgr.initialize()
        self.conn = self.db_mgr.connection

    def tearDown(self) -> None:
        self.db_mgr.close()
        self.tmp_dir.cleanup()

    def test_safe_html_converts_stray_lt_gt_to_latex(self) -> None:
        raw = 'If $a < b$ and $c > 0$, then:<br><ul><li>$\\langle x, y \\rangle > 0$</li></ul><img src="morphism://media/abc.svg">'
        sanitized = sanitize_math_html(raw)
        self.assertIn(r"$a \lt  b$", sanitized)
        self.assertIn(r"$c \gt  0$", sanitized)
        self.assertIn("<br><ul><li>", sanitized)
        self.assertIn('</li></ul><img src="morphism://media/abc.svg">', sanitized)

    def test_dsl_compile_and_cycle_detection(self) -> None:
        compiler = DSLCompiler(self.conn)
        valid_dsl = """
@course "Galois Theory"
@folder "Algebra/Fields"

@note field_ext
title: "Field Extension"
mode: standard
tags: [galois_theory, field_extensions, definition]
---
Q: Define a finite field extension $L / K$ with $[L:K] < \\infty$.
A: $L$ is a finite-dimensional vector space over $K$.
---

@note galois_corr
title: "Fundamental Theorem of Galois Theory"
mode: cloze
tags: [galois_theory, fundamental_theorem_of_galois_theory, theorem]
deps: [field_ext]
---
[step 1: Subgroup to Intermediate Field]
Q: Map $H \\le \\text{Gal}(L/K)$ to an intermediate field.
A: $H \\mapsto L^H = \\{x \\in L : \\sigma(x) = x \\text{ for all } \\sigma \\in H\\}$.
[step 2: Intermediate Field to Subgroup]
Q: Map an intermediate field $E$ to a subgroup of $\\text{Gal}(L/K)$.
A: $E \\mapsto \\text{Gal}(L/E)$.
---
"""
        res = compiler.compile_and_commit(valid_dsl, auto_layout=True)
        self.assertFalse(res.has_errors)
        self.assertEqual(res.notes_created, 2)
        self.assertEqual(res.edges_created, 1)
        self.assertIsNotNone(res.course_id)

        n_repo = NoteRepository(self.conn)
        notes = n_repo.list_by_course(res.course_id or 0)
        self.assertEqual(len(notes), 2)
        self.assertIn(r"\lt ", notes[0].cards[0].front_html)

        # Cycle detection test
        cyclic_dsl = """
@course "Cyclic"
@note n1
deps: [n2]
---
Q: q1
A: a1
---
@note n2
deps: [n1]
---
Q: q2
A: a2
---
"""
        cyc_res = compiler.check_only(cyclic_dsl)
        self.assertTrue(cyc_res.has_errors)


if __name__ == "__main__":
    unittest.main()
