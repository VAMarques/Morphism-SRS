from __future__ import annotations

from pathlib import Path
import re
import sqlite3
import tempfile
import zipfile

from morphism_srs.config import get_project_root
from morphism_srs.domain.models import generate_uuid
from morphism_srs.storage.media_vault import MediaVault
from morphism_srs.storage.unit_of_work import UnitOfWork


class MpkgService:
    """
    Packs and unpacks .mpkg (ZIP) deck archives containing a pure SQLite3 database
    (morphism.db) and media assets. Pure relational architecture without JSON.
    """

    MEDIA_REF_RE = re.compile(r"morphism://media/([a-zA-Z0-9_.-]+)")

    def __init__(self, conn: sqlite3.Connection, media_vault: MediaVault) -> None:
        self.conn = conn
        self.media_vault = media_vault

    def export_mpkg(
        self,
        course_id: int,
        target_path: Path,
        include_scheduling: bool = False,
    ) -> None:
        """
        Exports a course into a pure SQL .mpkg package containing morphism.db and media assets.
        """
        schema_path = Path(__file__).resolve().parents[2] / "storage" / "schema_v2.sql"
        if not schema_path.exists():
            schema_path = get_project_root() / "src" / "morphism_srs" / "storage" / "schema_v2.sql"

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            temp_db_path = tmp_root / "morphism.db"

            temp_conn = sqlite3.connect(temp_db_path)
            try:
                temp_conn.row_factory = sqlite3.Row
                with schema_path.open("r", encoding="utf-8") as f:
                    temp_conn.executescript(f.read())

                # 1. Fetch course from main database
                cur = self.conn.cursor()
                cur.execute("SELECT * FROM courses WHERE id = ?", (course_id,))
                c_row = cur.fetchone()
                if not c_row:
                    raise ValueError(f"Course {course_id} not found")

                folder_id = c_row["folder_id"]
                if folder_id:
                    cur.execute("SELECT * FROM course_folders WHERE id = ?", (folder_id,))
                    f_row = cur.fetchone()
                    if f_row:
                        temp_conn.execute(
                            """
                            INSERT INTO course_folders (id, parent_id, name, display_order, fsrs_weights_json, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                f_row["id"],
                                f_row["parent_id"],
                                f_row["name"],
                                f_row["display_order"],
                                f_row["fsrs_weights_json"],
                                f_row["created_at"],
                                f_row["updated_at"],
                            ),
                        )

                temp_conn.execute(
                    """
                    INSERT INTO courses (id, uuid, folder_id, name, color_hex, description, display_order, desired_retention, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        c_row["id"],
                        c_row["uuid"],
                        c_row["folder_id"],
                        c_row["name"],
                        c_row["color_hex"],
                        c_row["description"],
                        c_row["display_order"],
                        c_row["desired_retention"],
                        c_row["created_at"],
                        c_row["updated_at"],
                    ),
                )

                # 2. Fetch notes belonging to this course
                cur.execute(
                    """
                    SELECT n.*, cn.pos_x AS course_pos_x, cn.pos_y AS course_pos_y
                    FROM notes n
                    JOIN course_notes cn ON cn.note_id = n.id
                    WHERE cn.course_id = ?
                    """,
                    (course_id,),
                )
                note_rows = cur.fetchall()
                note_ids = [n["id"] for n in note_rows]

                referenced_media_names: set[str] = set()

                for nr in note_rows:
                    if nr["premise_html"]:
                        referenced_media_names.update(self.MEDIA_REF_RE.findall(nr["premise_html"]))

                    temp_conn.execute(
                        """
                        INSERT INTO notes (id, uuid, course_id, external_key, title, premise_html, pos_x, pos_y, review_mode, desired_retention, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            nr["id"],
                            nr["uuid"],
                            nr["course_id"],
                            nr["external_key"],
                            nr["title"],
                            nr["premise_html"],
                            nr["course_pos_x"] if nr["course_pos_x"] is not None else nr["pos_x"],
                            nr["course_pos_y"] if nr["course_pos_y"] is not None else nr["pos_y"],
                            nr["review_mode"],
                            nr["desired_retention"],
                            nr["created_at"],
                            nr["updated_at"],
                        ),
                    )
                    temp_conn.execute(
                        "INSERT INTO course_notes (course_id, note_id, pos_x, pos_y) VALUES (?, ?, ?, ?)",
                        (course_id, nr["id"], nr["course_pos_x"], nr["course_pos_y"]),
                    )

                # 3. Fetch cards belonging to these notes
                if note_ids:
                    placeholders = ",".join("?" for _ in note_ids)
                    cur.execute(
                        f"SELECT * FROM cards WHERE note_id IN ({placeholders}) ORDER BY step_order, id",
                        note_ids,
                    )
                    card_rows = cur.fetchall()
                    card_ids = [cr["id"] for cr in card_rows]

                    for cr in card_rows:
                        if cr["front_html"]:
                            referenced_media_names.update(self.MEDIA_REF_RE.findall(cr["front_html"]))
                        if cr["back_html"]:
                            referenced_media_names.update(self.MEDIA_REF_RE.findall(cr["back_html"]))
                        if cr["hint_html"]:
                            referenced_media_names.update(self.MEDIA_REF_RE.findall(cr["hint_html"]))

                        temp_conn.execute(
                            """
                            INSERT INTO cards (id, uuid, note_id, step_order, title, front_html, back_html, hint_html, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                cr["id"],
                                cr["uuid"],
                                cr["note_id"],
                                cr["step_order"],
                                cr["title"],
                                cr["front_html"],
                                cr["back_html"],
                                cr["hint_html"],
                                cr["created_at"],
                                cr["updated_at"],
                            ),
                        )

                    if include_scheduling and card_ids:
                        c_placeholders = ",".join("?" for _ in card_ids)
                        cur.execute(
                            f"SELECT * FROM card_schedules WHERE card_id IN ({c_placeholders})",
                            card_ids,
                        )
                        for sr in cur.fetchall():
                            temp_conn.execute(
                                """
                                INSERT OR REPLACE INTO card_schedules (
                                    card_id, state, step, stability, difficulty, due_at,
                                    last_review_at, reps, lapses, scheduled_days, elapsed_days,
                                    is_suspended, is_buried
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    sr["card_id"],
                                    sr["state"],
                                    sr["step"],
                                    sr["stability"],
                                    sr["difficulty"],
                                    sr["due_at"],
                                    sr["last_review_at"],
                                    sr["reps"],
                                    sr["lapses"],
                                    sr["scheduled_days"],
                                    sr["elapsed_days"],
                                    sr["is_suspended"],
                                    sr["is_buried"],
                                ),
                            )

                        cur.execute(
                            f"SELECT * FROM review_logs WHERE card_id IN ({c_placeholders})",
                            card_ids,
                        )
                        for lr in cur.fetchall():
                            temp_conn.execute(
                                """
                                INSERT INTO review_logs (
                                    id, uuid, card_id, rating, reviewed_at, duration_ms,
                                    prev_state, prev_step, prev_stability, prev_difficulty,
                                    prev_due_at, prev_last_review_at, new_state, new_step,
                                    new_stability, new_difficulty, new_due_at, elapsed_days,
                                    scheduled_days
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    lr["id"],
                                    lr["uuid"],
                                    lr["card_id"],
                                    lr["rating"],
                                    lr["reviewed_at"],
                                    lr["duration_ms"],
                                    lr["prev_state"],
                                    lr["prev_step"],
                                    lr["prev_stability"],
                                    lr["prev_difficulty"],
                                    lr["prev_due_at"],
                                    lr["prev_last_review_at"],
                                    lr["new_state"],
                                    lr["new_step"],
                                    lr["new_stability"],
                                    lr["new_difficulty"],
                                    lr["new_due_at"],
                                    lr["elapsed_days"],
                                    lr["scheduled_days"],
                                ),
                            )

                    # Tags and note_tags
                    cur.execute(
                        f"""
                        SELECT t.id AS tag_id, t.name, nt.note_id
                        FROM note_tags nt
                        JOIN tags t ON t.id = nt.tag_id
                        WHERE nt.note_id IN ({placeholders})
                        """,
                        note_ids,
                    )
                    for tr in cur.fetchall():
                        temp_conn.execute(
                            "INSERT OR IGNORE INTO tags (id, name) VALUES (?, ?)",
                            (tr["tag_id"], tr["name"]),
                        )
                        temp_conn.execute(
                            "INSERT OR IGNORE INTO note_tags (note_id, tag_id) VALUES (?, ?)",
                            (tr["note_id"], tr["tag_id"]),
                        )

                # 4. Edges
                cur.execute("SELECT * FROM edges WHERE course_id = ?", (course_id,))
                for er in cur.fetchall():
                    temp_conn.execute(
                        """
                        INSERT INTO edges (id, uuid, course_id, source_note_id, target_note_id, relation_type, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            er["id"],
                            er["uuid"],
                            er["course_id"],
                            er["source_note_id"],
                            er["target_note_id"],
                            er["relation_type"],
                            er["created_at"],
                        ),
                    )

                # 5. Media assets metadata & packing
                media_files_to_pack: list[tuple[Path, str]] = []
                for fname in referenced_media_names:
                    resolved = self.media_vault.resolve_path(fname)
                    if resolved and resolved.is_file():
                        media_files_to_pack.append((resolved, resolved.name))
                        # Check if registered in media_assets
                        stem = resolved.stem
                        cur.execute(
                            "SELECT * FROM media_assets WHERE sha256_hash = ? OR original_name = ?",
                            (stem, fname),
                        )
                        ma = cur.fetchone()
                        if ma:
                            temp_conn.execute(
                                """
                                INSERT OR IGNORE INTO media_assets (sha256_hash, original_name, mime_type, byte_size, created_at)
                                VALUES (?, ?, ?, ?, ?)
                                """,
                                (
                                    ma["sha256_hash"],
                                    ma["original_name"],
                                    ma["mime_type"],
                                    ma["byte_size"],
                                    ma["created_at"],
                                ),
                            )

                temp_conn.commit()
            finally:
                temp_conn.close()

            # Pack temporary morphism.db and media assets into target ZIP
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(target_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.write(temp_db_path, arcname="morphism.db")
                for src_file, arc_name in media_files_to_pack:
                    zf.write(src_file, arcname=f"media/{arc_name}")

    def import_mpkg(self, mpkg_path: Path, include_scheduling: bool = True) -> int:
        """
        Imports an .mpkg package containing morphism.db and media/ assets directly
        into the main SQLite database using UUID-preserving SQL upserts.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            with zipfile.ZipFile(mpkg_path, "r") as zf:
                names = set(zf.namelist())
                if "morphism.db" not in names:
                    raise ValueError("Invalid .mpkg archive: missing morphism.db SQLite database")

                # Extract media files directly to media vault
                for member in names:
                    if member.startswith("media/") and not member.endswith("/"):
                        raw_bytes = zf.read(member)
                        fname = Path(member).name
                        self.media_vault.store_bytes(raw_bytes, fname)

                # Extract morphism.db
                db_path = tmp_root / "morphism.db"
                with db_path.open("wb") as f:
                    f.write(zf.read("morphism.db"))

            # Read from extracted package database
            pkg_conn = sqlite3.connect(db_path)
            try:
                pkg_conn.row_factory = sqlite3.Row
                pkg_cur = pkg_conn.cursor()

                with UnitOfWork(self.conn):
                    # 1. Course import
                    pkg_cur.execute("SELECT * FROM courses LIMIT 1")
                    pkg_course = pkg_cur.fetchone()
                    if not pkg_course:
                        raise ValueError("Invalid .mpkg package: no course record found")

                    cur = self.conn.cursor()
                    cur.execute("SELECT id FROM courses WHERE uuid = ?", (pkg_course["uuid"],))
                    existing_c = cur.fetchone()

                    if existing_c:
                        course_id = existing_c[0]
                        cur.execute(
                            """
                            UPDATE courses
                            SET name = ?, color_hex = ?, description = ?, desired_retention = ?, updated_at = CURRENT_TIMESTAMP
                            WHERE id = ?
                            """,
                            (
                                pkg_course["name"],
                                pkg_course["color_hex"],
                                pkg_course["description"],
                                pkg_course["desired_retention"],
                                course_id,
                            ),
                        )
                    else:
                        cur.execute(
                            """
                            INSERT INTO courses (uuid, name, color_hex, description, display_order, desired_retention)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                pkg_course["uuid"],
                                pkg_course["name"],
                                pkg_course["color_hex"],
                                pkg_course["description"],
                                pkg_course["display_order"],
                                pkg_course["desired_retention"],
                            ),
                        )
                        course_id = cur.lastrowid
                        assert course_id is not None

                    # 2. Notes import
                    pkg_cur.execute("SELECT * FROM notes")
                    pkg_notes = pkg_cur.fetchall()
                    old_to_new_note_ids: dict[int, int] = {}

                    for pn in pkg_notes:
                        cur.execute("SELECT id FROM notes WHERE uuid = ?", (pn["uuid"],))
                        existing_n = cur.fetchone()

                        if existing_n:
                            note_id = existing_n[0]
                            cur.execute(
                                """
                                UPDATE notes
                                SET title = ?, premise_html = ?, pos_x = ?, pos_y = ?, review_mode = ?, desired_retention = ?, updated_at = CURRENT_TIMESTAMP
                                WHERE id = ?
                                """,
                                (
                                    pn["title"],
                                    pn["premise_html"],
                                    pn["pos_x"],
                                    pn["pos_y"],
                                    pn["review_mode"],
                                    pn["desired_retention"],
                                    note_id,
                                ),
                            )
                        else:
                            cur.execute(
                                """
                                INSERT INTO notes (uuid, course_id, external_key, title, premise_html, pos_x, pos_y, review_mode, desired_retention)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    pn["uuid"],
                                    course_id,
                                    pn["external_key"],
                                    pn["title"],
                                    pn["premise_html"],
                                    pn["pos_x"],
                                    pn["pos_y"],
                                    pn["review_mode"],
                                    pn["desired_retention"],
                                ),
                            )
                            note_id = cur.lastrowid
                            assert note_id is not None

                        old_to_new_note_ids[pn["id"]] = note_id
                        cur.execute(
                            "INSERT OR REPLACE INTO course_notes (course_id, note_id, pos_x, pos_y) VALUES (?, ?, ?, ?)",
                            (course_id, note_id, pn["pos_x"], pn["pos_y"]),
                        )

                    # 3. Cards import
                    pkg_cur.execute("SELECT * FROM cards")
                    for pc in pkg_cur.fetchall():
                        target_note_id = old_to_new_note_ids.get(pc["note_id"])
                        if not target_note_id:
                            continue

                        cur.execute("SELECT id FROM cards WHERE uuid = ?", (pc["uuid"],))
                        existing_c = cur.fetchone()

                        if existing_c:
                            card_id = existing_c[0]
                            cur.execute(
                                """
                                UPDATE cards
                                SET step_order = ?, title = ?, front_html = ?, back_html = ?, hint_html = ?, updated_at = CURRENT_TIMESTAMP
                                WHERE id = ?
                                """,
                                (
                                    pc["step_order"],
                                    pc["title"],
                                    pc["front_html"],
                                    pc["back_html"],
                                    pc["hint_html"],
                                    card_id,
                                ),
                            )
                        else:
                            cur.execute(
                                """
                                INSERT INTO cards (uuid, note_id, step_order, title, front_html, back_html, hint_html)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    pc["uuid"],
                                    target_note_id,
                                    pc["step_order"],
                                    pc["title"],
                                    pc["front_html"],
                                    pc["back_html"],
                                    pc["hint_html"],
                                ),
                            )
                            card_id = cur.lastrowid
                            assert card_id is not None

                        if include_scheduling:
                            pkg_cur.execute("SELECT * FROM card_schedules WHERE card_id = ?", (pc["id"],))
                            psched = pkg_cur.fetchone()
                            if psched:
                                cur.execute(
                                    """
                                    INSERT OR REPLACE INTO card_schedules (
                                        card_id, state, step, stability, difficulty, due_at,
                                        last_review_at, reps, lapses, scheduled_days, elapsed_days,
                                        is_suspended, is_buried
                                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                    """,
                                    (
                                        card_id,
                                        psched["state"],
                                        psched["step"],
                                        psched["stability"],
                                        psched["difficulty"],
                                        psched["due_at"],
                                        psched["last_review_at"],
                                        psched["reps"],
                                        psched["lapses"],
                                        psched["scheduled_days"],
                                        psched["elapsed_days"],
                                        psched["is_suspended"],
                                        psched["is_buried"],
                                    ),
                                )

                            pkg_cur.execute("SELECT * FROM review_logs WHERE card_id = ?", (pc["id"],))
                            for plog in pkg_cur.fetchall():
                                cur.execute("SELECT 1 FROM review_logs WHERE uuid = ?", (plog["uuid"],))
                                if not cur.fetchone():
                                    cur.execute(
                                        """
                                        INSERT INTO review_logs (
                                            uuid, card_id, rating, reviewed_at, duration_ms,
                                            prev_state, prev_step, prev_stability, prev_difficulty,
                                            prev_due_at, prev_last_review_at, new_state, new_step,
                                            new_stability, new_difficulty, new_due_at, elapsed_days,
                                            scheduled_days
                                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                        """,
                                        (
                                            plog["uuid"],
                                            card_id,
                                            plog["rating"],
                                            plog["reviewed_at"],
                                            plog["duration_ms"],
                                            plog["prev_state"],
                                            plog["prev_step"],
                                            plog["prev_stability"],
                                            plog["prev_difficulty"],
                                            plog["prev_due_at"],
                                            plog["prev_last_review_at"],
                                            plog["new_state"],
                                            plog["new_step"],
                                            plog["new_stability"],
                                            plog["new_difficulty"],
                                            plog["new_due_at"],
                                            plog["elapsed_days"],
                                            plog["scheduled_days"],
                                        ),
                                    )

                    # 4. Edges import
                    pkg_cur.execute("SELECT * FROM edges")
                    for pe in pkg_cur.fetchall():
                        src_id = old_to_new_note_ids.get(pe["source_note_id"])
                        tgt_id = old_to_new_note_ids.get(pe["target_note_id"])
                        if src_id and tgt_id:
                            cur.execute(
                                "SELECT 1 FROM edges WHERE course_id = ? AND source_note_id = ? AND target_note_id = ?",
                                (course_id, src_id, tgt_id),
                            )
                            if not cur.fetchone():
                                edge_uuid = pe["uuid"] or generate_uuid()
                                cur.execute(
                                    """
                                    INSERT INTO edges (uuid, course_id, source_note_id, target_note_id, relation_type)
                                    VALUES (?, ?, ?, ?, ?)
                                    """,
                                    (
                                        edge_uuid,
                                        course_id,
                                        src_id,
                                        tgt_id,
                                        pe["relation_type"] or "prerequisite",
                                    ),
                                )

                    # 5. Media assets & associations
                    pkg_cur.execute("SELECT * FROM media_assets")
                    for pma in pkg_cur.fetchall():
                        cur.execute(
                            """
                            INSERT OR IGNORE INTO media_assets (sha256_hash, original_name, mime_type, byte_size, created_at)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (
                                pma["sha256_hash"],
                                pma["original_name"],
                                pma["mime_type"],
                                pma["byte_size"],
                                pma["created_at"],
                            ),
                        )
            finally:
                pkg_conn.close()

            return course_id
