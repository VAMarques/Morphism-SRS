from __future__ import annotations

import csv
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class DatabaseManager:
    """Manages the SQLite v2 connection, PRAGMAs, schema initialization, and tag seeding."""

    def __init__(self, db_path: Path, schema_path: Path, tags_csv_path: Path | None = None) -> None:
        self.db_path = db_path
        self.schema_path = schema_path
        self.tags_csv_path = tags_csv_path
        self._conn: sqlite3.Connection | None = None

    @property
    def connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(
                str(self.db_path),
                detect_types=0,
                isolation_level=None,  # Explicit transaction management via UnitOfWork / BEGIN
                check_same_thread=False,
            )
            self._conn.row_factory = sqlite3.Row
            self._apply_pragmas(self._conn)
        return self._conn

    @staticmethod
    def _apply_pragmas(conn: sqlite3.Connection) -> None:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA temp_store = MEMORY;")
        conn.execute("PRAGMA cache_size = -64000;")

    def initialize(self) -> None:
        """Executes schema_v2.sql, runs migrations, and seeds default tags if not yet seeded."""
        conn = self.connection
        if self.schema_path.exists():
            ddl = self.schema_path.read_text(encoding="utf-8")
            conn.executescript(ddl)
            self._apply_pragmas(conn)

        # Migrate course_notes if empty but notes exist
        try:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM course_notes;").fetchone()
            if row and row["cnt"] == 0:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO course_notes (course_id, note_id, pos_x, pos_y, is_pinned)
                    SELECT course_id, id, pos_x, pos_y, is_pinned FROM notes WHERE course_id IS NOT NULL;
                    """
                )
        except Exception:
            pass

        if self.tags_csv_path and self.tags_csv_path.exists():
            self._seed_default_tags(conn, self.tags_csv_path)

    def _seed_default_tags(self, conn: sqlite3.Connection, csv_path: Path) -> None:
        row = conn.execute("SELECT COUNT(*) AS cnt FROM tags;").fetchone()
        if row and row["cnt"] > 0:
            return

        tags_to_insert: list[tuple[str, str, str, str]] = []
        with csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for item in reader:
                tag_name = (item.get("tag_name") or item.get("tag") or "").strip().lower()
                category = (item.get("category") or "general").strip().lower()
                scope = (item.get("scope") or "standard").strip().lower()
                color = (item.get("color_hex") or "#cba6f7").strip()
                if tag_name:
                    tags_to_insert.append((tag_name, category, scope, color))

        if tags_to_insert:
            conn.execute("BEGIN;")
            try:
                conn.executemany(
                    "INSERT OR IGNORE INTO tags (name, category, scope, color_hex) VALUES (?, ?, ?, ?);",
                    tags_to_insert,
                )
                conn.execute("COMMIT;")
            except Exception:
                conn.execute("ROLLBACK;")
                raise

    def create_backup(self, backups_dir: Path, max_backups: int = 10) -> Path | None:
        """Creates a timestamped SQLite backup and prunes older backups."""
        if not self.db_path.exists():
            return None
        backups_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        dest = backups_dir / f"morphism_v2_{stamp}.sqlite3"
        if self._conn is not None:
            bck = sqlite3.connect(str(dest))
            with bck:
                self._conn.backup(bck)
            bck.close()
        else:
            shutil.copy2(self.db_path, dest)

        backups = sorted(backups_dir.glob("morphism_v2_*.sqlite3"), key=lambda p: p.stat().st_mtime)
        while len(backups) > max_backups:
            oldest = backups.pop(0)
            oldest.unlink(missing_ok=True)
        return dest

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None
