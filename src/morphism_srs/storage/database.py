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

        # Ensure notes.course_id is nullable (migrating legacy databases)
        try:
            cursor = conn.execute("PRAGMA table_info(notes);")
            cols = {row["name"]: row for row in cursor.fetchall()}
            if "course_id" in cols and cols["course_id"]["notnull"] == 1:
                conn.execute("PRAGMA foreign_keys = OFF;")
                conn.execute("BEGIN;")
                conn.execute("""
                    CREATE TABLE notes_nullable_cid (
                        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                        uuid                TEXT NOT NULL UNIQUE,
                        course_id           INTEGER REFERENCES courses(id) ON DELETE SET NULL,
                        external_key        TEXT,
                        title               TEXT NOT NULL CHECK (length(trim(title)) > 0),
                        premise_html        TEXT NOT NULL DEFAULT '',
                        pos_x               REAL NOT NULL DEFAULT 0.0,
                        pos_y               REAL NOT NULL DEFAULT 0.0,
                        review_mode         TEXT NOT NULL DEFAULT 'standard' CHECK (review_mode IN ('standard', 'serial', 'cloze')),
                        desired_retention   REAL CHECK (desired_retention IS NULL OR (desired_retention >= 0.70 AND desired_retention <= 0.99)),
                        is_pinned           INTEGER NOT NULL DEFAULT 0 CHECK (is_pinned IN (0, 1)),
                        created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                        updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                        UNIQUE (course_id, external_key)
                    ) STRICT;
                """)
                conn.execute("""
                    INSERT INTO notes_nullable_cid
                    SELECT id, uuid, course_id, external_key, title, premise_html, pos_x, pos_y, review_mode, desired_retention, is_pinned, created_at, updated_at
                    FROM notes;
                """)
                conn.execute("DROP TABLE notes;")
                conn.execute("ALTER TABLE notes_nullable_cid RENAME TO notes;")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_notes_course ON notes(course_id);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_notes_mode ON notes(review_mode);")
                conn.execute("COMMIT;")
                conn.execute("PRAGMA foreign_keys = ON;")
        except Exception:
            try:
                conn.execute("ROLLBACK;")
            except Exception:
                pass

        # Ensure gamification_stats table and initial singleton row exist
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS gamification_stats (
                    id                  INTEGER PRIMARY KEY CHECK (id = 1),
                    streak_count        INTEGER NOT NULL DEFAULT 0,
                    total_xp            REAL NOT NULL DEFAULT 0.0,
                    last_login_at       TEXT,
                    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                ) STRICT;
            """)
            conn.execute("INSERT OR IGNORE INTO gamification_stats (id, streak_count, total_xp, last_login_at) VALUES (1, 0, 0.0, NULL);")
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
