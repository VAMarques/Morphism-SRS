from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from morphism_srs.domain.models import CourseFolderModel


class FolderRepository:
    """Repository for hierarchical course_folders with recursive FSRS weight inheritance."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    @staticmethod
    def _row_to_model(row: sqlite3.Row) -> CourseFolderModel:
        return CourseFolderModel(
            id=int(row["id"]),
            uuid=str(row["uuid"]),
            name=str(row["name"]),
            parent_id=int(row["parent_id"]) if row["parent_id"] is not None else None,
            display_order=int(row["display_order"]),
            is_expanded=bool(row["is_expanded"]),
            fsrs_weights_json=str(row["fsrs_weights_json"]) if row["fsrs_weights_json"] is not None else None,
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def list_all(self) -> list[CourseFolderModel]:
        rows = self.conn.execute(
            "SELECT * FROM course_folders ORDER BY display_order ASC, name ASC;"
        ).fetchall()
        return [self._row_to_model(r) for r in rows]

    def get_by_id(self, folder_id: int) -> CourseFolderModel | None:
        row = self.conn.execute("SELECT * FROM course_folders WHERE id = ?;", (folder_id,)).fetchone()
        return self._row_to_model(row) if row else None

    def get_by_uuid(self, folder_uuid: str) -> CourseFolderModel | None:
        row = self.conn.execute("SELECT * FROM course_folders WHERE uuid = ?;", (folder_uuid,)).fetchone()
        return self._row_to_model(row) if row else None

    def create(self, folder: CourseFolderModel) -> CourseFolderModel:
        now = datetime.now(timezone.utc).isoformat()
        folder.created_at = folder.created_at or now
        folder.updated_at = now
        cur = self.conn.execute(
            """
            INSERT INTO course_folders (uuid, name, parent_id, display_order, is_expanded, fsrs_weights_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                folder.uuid,
                folder.name,
                folder.parent_id,
                folder.display_order,
                1 if folder.is_expanded else 0,
                folder.fsrs_weights_json,
                folder.created_at,
                folder.updated_at,
            ),
        )
        folder.id = int(cur.lastrowid)
        return folder

    def update(self, folder: CourseFolderModel) -> None:
        folder.updated_at = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """
            UPDATE course_folders
            SET name = ?, parent_id = ?, display_order = ?, is_expanded = ?, fsrs_weights_json = ?, updated_at = ?
            WHERE id = ?;
            """,
            (
                folder.name,
                folder.parent_id,
                folder.display_order,
                1 if folder.is_expanded else 0,
                folder.fsrs_weights_json,
                folder.updated_at,
                folder.id,
            ),
        )

    def delete(self, folder_id: int) -> None:
        self.conn.execute("DELETE FROM course_folders WHERE id = ?;", (folder_id,))

    def ensure_folder_path(self, path_parts: list[str]) -> int | None:
        """Ensures a chain of folder names exists and returns the leaf folder_id."""
        parent_id: int | None = None
        for part in path_parts:
            clean = part.strip()
            if not clean:
                continue
            if parent_id is None:
                row = self.conn.execute(
                    "SELECT id FROM course_folders WHERE parent_id IS NULL AND name = ?;",
                    (clean,),
                ).fetchone()
            else:
                row = self.conn.execute(
                    "SELECT id FROM course_folders WHERE parent_id = ? AND name = ?;",
                    (parent_id, clean),
                ).fetchone()
            if row:
                parent_id = int(row["id"])
            else:
                created = self.create(CourseFolderModel(name=clean, parent_id=parent_id))
                parent_id = created.id
        return parent_id

    def resolve_effective_fsrs_weights(self, folder_id: int | None) -> str | None:
        """Walks up the folder tree via recursive CTE to find the closest non-null fsrs_weights_json."""
        if folder_id is not None:
            row = self.conn.execute(
                """
                WITH RECURSIVE ancestors(id, parent_id, weights, depth) AS (
                    SELECT id, parent_id, fsrs_weights_json, 0
                    FROM course_folders
                    WHERE id = ?
                    UNION ALL
                    SELECT f.id, f.parent_id, f.fsrs_weights_json, a.depth + 1
                    FROM course_folders f
                    JOIN ancestors a ON f.id = a.parent_id
                    WHERE a.depth < 32
                )
                SELECT weights FROM ancestors WHERE weights IS NOT NULL ORDER BY depth ASC LIMIT 1;
                """,
                (folder_id,),
            ).fetchone()
            if row and row["weights"]:
                return str(row["weights"])

        global_row = self.conn.execute(
            "SELECT value_json FROM app_meta WHERE key = 'global_fsrs_weights';"
        ).fetchone()
        return str(global_row["value_json"]) if global_row and global_row["value_json"] else None

    def set_global_fsrs_weights(self, weights_json: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO app_meta (key, value_json) VALUES ('global_fsrs_weights', ?);",
            (weights_json,),
        )

    def get_descendant_folder_ids(self, root_folder_id: int) -> list[int]:
        rows = self.conn.execute(
            """
            WITH RECURSIVE tree(id) AS (
                SELECT ?
                UNION ALL
                SELECT f.id FROM course_folders f JOIN tree t ON f.parent_id = t.id
            )
            SELECT id FROM tree;
            """,
            (root_folder_id,),
        ).fetchall()
        return [int(r["id"]) for r in rows]
