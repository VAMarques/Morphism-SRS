from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from morphism_srs.domain.models import ScratchbookPageModel


class ScratchRepository:
    """Repository for scratchbook_pages stored in SQLite."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    @staticmethod
    def _row_to_model(row: sqlite3.Row) -> ScratchbookPageModel:
        return ScratchbookPageModel(
            id=int(row["id"]),
            uuid=str(row["uuid"]),
            title=str(row["title"]),
            content_text=str(row["content_text"]),
            display_order=int(row["display_order"]),
            updated_at=str(row["updated_at"]),
        )

    def list_all(self) -> list[ScratchbookPageModel]:
        rows = self.conn.execute(
            "SELECT * FROM scratchbook_pages ORDER BY display_order ASC, id ASC;"
        ).fetchall()
        return [self._row_to_model(r) for r in rows]

    def get_by_id(self, page_id: int) -> ScratchbookPageModel | None:
        row = self.conn.execute(
            "SELECT * FROM scratchbook_pages WHERE id = ?;",
            (page_id,),
        ).fetchone()
        return self._row_to_model(row) if row else None

    def create(self, page: ScratchbookPageModel) -> ScratchbookPageModel:
        now = datetime.now(timezone.utc).isoformat()
        page.updated_at = now
        cur = self.conn.execute(
            """
            INSERT INTO scratchbook_pages (uuid, title, content_text, display_order, updated_at)
            VALUES (?, ?, ?, ?, ?);
            """,
            (page.uuid, page.title, page.content_text, page.display_order, page.updated_at),
        )
        page.id = int(cur.lastrowid)
        return page

    def update(self, page: ScratchbookPageModel) -> None:
        page.updated_at = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """
            UPDATE scratchbook_pages
            SET title = ?, content_text = ?, display_order = ?, updated_at = ?
            WHERE id = ?;
            """,
            (page.title, page.content_text, page.display_order, page.updated_at, page.id),
        )

    def delete(self, page_id: int) -> None:
        self.conn.execute("DELETE FROM scratchbook_pages WHERE id = ?;", (page_id,))
