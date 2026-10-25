from __future__ import annotations

from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT_DIR = Path(__file__).resolve().parent.parent
TOOLS_DIR = ROOT_DIR / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import migrate_proto1  # noqa: E402


class TestStandaloneProto1Migration(unittest.TestCase):
    def test_migrate_proto1_standalone_isolation_and_real_data(self) -> None:
        # 1. Verify tools/migrate_proto1.py does NOT import anything from morphism_srs
        source_code = (TOOLS_DIR / "migrate_proto1.py").read_text(encoding="utf-8")
        self.assertNotIn("from morphism_srs", source_code)
        self.assertNotIn("import morphism_srs", source_code)

        # 2. If Prototype 1 repo exists at c:\repos\New SRS Project, run real migration into a temp DB
        proto1_path = Path(r"c:\repos\New SRS Project")
        if not proto1_path.exists():
            return

        with tempfile.TemporaryDirectory() as tmp:
            target_db = Path(tmp) / "migrated_v2.sqlite3"
            schema_sql = ROOT_DIR / "src" / "morphism_srs" / "storage" / "schema_v2.sql"
            summary = migrate_proto1.migrate_proto1_to_v2(proto1_path, target_db, schema_sql)

            self.assertGreater(summary["courses"], 0)
            self.assertGreater(summary["notes"], 0)
            self.assertGreater(summary["cards"], 0)

            conn = sqlite3.connect(str(target_db))
            modes = {
                r[0]
                for r in conn.execute("SELECT DISTINCT review_mode FROM notes;").fetchall()
            }
            self.assertTrue(modes.issubset({"standard", "serial", "cloze"}))
            conn.close()


if __name__ == "__main__":
    unittest.main()
