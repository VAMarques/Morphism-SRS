from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from morphism_srs.domain.models import CourseModel


class CourseRepository:
    """Repository for courses and course-level statistics."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    @staticmethod
    def _row_to_model(row: sqlite3.Row) -> CourseModel:
        return CourseModel(
            id=int(row["id"]),
            uuid=str(row["uuid"]),
            name=str(row["name"]),
            folder_id=int(row["folder_id"]) if row["folder_id"] is not None else None,
            description=str(row["description"]),
            color_hex=str(row["color_hex"]),
            desired_retention=float(row["desired_retention"]),
            display_order=int(row["display_order"]),
            is_archived=bool(row["is_archived"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def list_all(self, include_archived: bool = False) -> list[CourseModel]:
        if include_archived:
            rows = self.conn.execute(
                "SELECT * FROM courses ORDER BY display_order ASC, name ASC;"
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM courses WHERE is_archived = 0 ORDER BY display_order ASC, name ASC;"
            ).fetchall()
        return [self._row_to_model(r) for r in rows]

    def get_by_id(self, course_id: int) -> CourseModel | None:
        row = self.conn.execute("SELECT * FROM courses WHERE id = ?;", (course_id,)).fetchone()
        return self._row_to_model(row) if row else None

    def get_by_name(self, name: str) -> CourseModel | None:
        row = self.conn.execute("SELECT * FROM courses WHERE name = ?;", (name,)).fetchone()
        return self._row_to_model(row) if row else None

    def get_by_uuid(self, course_uuid: str) -> CourseModel | None:
        row = self.conn.execute("SELECT * FROM courses WHERE uuid = ?;", (course_uuid,)).fetchone()
        return self._row_to_model(row) if row else None

    def create(self, course: CourseModel) -> CourseModel:
        now = datetime.now(timezone.utc).isoformat()
        course.created_at = course.created_at or now
        course.updated_at = now
        cur = self.conn.execute(
            """
            INSERT INTO courses (uuid, name, folder_id, description, color_hex, desired_retention, display_order, is_archived, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                course.uuid,
                course.name,
                course.folder_id,
                course.description,
                course.color_hex,
                course.desired_retention,
                course.display_order,
                1 if course.is_archived else 0,
                course.created_at,
                course.updated_at,
            ),
        )
        course.id = int(cur.lastrowid)
        return course

    def update(self, course: CourseModel) -> None:
        course.updated_at = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """
            UPDATE courses
            SET name = ?, folder_id = ?, description = ?, color_hex = ?, desired_retention = ?, display_order = ?, is_archived = ?, updated_at = ?
            WHERE id = ?;
            """,
            (
                course.name,
                course.folder_id,
                course.description,
                course.color_hex,
                course.desired_retention,
                course.display_order,
                1 if course.is_archived else 0,
                course.updated_at,
                course.id,
            ),
        )

    def delete(self, course_id: int) -> None:
        self.conn.execute("DELETE FROM courses WHERE id = ?;", (course_id,))

    def get_course_counts(self, now_iso: str | None = None) -> dict[int, dict[str, int]]:
        """Returns {course_id: {'notes': int, 'cards': int, 'due': int, 'new': int}}."""
        now_str = now_iso or datetime.now(timezone.utc).isoformat()
        rows = self.conn.execute(
            """
            SELECT
                c.id AS course_id,
                COUNT(DISTINCT n.id) AS note_count,
                COUNT(cd.id) AS card_count,
                SUM(CASE WHEN cs.is_suspended = 0 AND cs.is_buried = 0 AND cs.state > 0 AND cs.due_at <= ? THEN 1 ELSE 0 END) AS due_count,
                SUM(CASE WHEN cs.is_suspended = 0 AND cs.is_buried = 0 AND cs.state = 0 THEN 1 ELSE 0 END) AS new_count
            FROM courses c
            LEFT JOIN notes n ON n.course_id = c.id
            LEFT JOIN cards cd ON cd.note_id = n.id
            LEFT JOIN card_schedules cs ON cs.card_id = cd.id
            GROUP BY c.id;
            """,
            (now_str,),
        ).fetchall()
        result: dict[int, dict[str, int]] = {}
        for r in rows:
            cid = int(r["course_id"])
            result[cid] = {
                "notes": int(r["note_count"] or 0),
                "cards": int(r["card_count"] or 0),
                "due": int(r["due_count"] or 0),
                "new": int(r["new_count"] or 0),
            }
        return result
