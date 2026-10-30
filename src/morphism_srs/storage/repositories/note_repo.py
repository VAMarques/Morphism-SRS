from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from morphism_srs.domain.enums import NoteReviewMode
from morphism_srs.domain.models import EdgeModel, NoteModel, TagModel
from morphism_srs.storage.repositories.card_repo import CardRepository


class NoteRepository:
    """Repository for notes, note_tags, tags, and dependency edges."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.card_repo = CardRepository(conn)

    @staticmethod
    def _row_to_note(row: sqlite3.Row) -> NoteModel:
        return NoteModel(
            id=int(row["id"]),
            uuid=str(row["uuid"]),
            course_id=int(row["course_id"]) if row["course_id"] is not None else None,
            external_key=str(row["external_key"]) if row["external_key"] is not None else None,
            title=str(row["title"]),
            premise_html=str(row["premise_html"]),
            pos_x=float(row["pos_x"]),
            pos_y=float(row["pos_y"]),
            review_mode=NoteReviewMode(str(row["review_mode"])),
            desired_retention=float(row["desired_retention"]) if row["desired_retention"] is not None else None,
            is_pinned=bool(row["is_pinned"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def get_by_id(self, note_id: int, include_children: bool = True) -> NoteModel | None:
        row = self.conn.execute("SELECT * FROM notes WHERE id = ?;", (note_id,)).fetchone()
        if not row:
            return None
        note = self._row_to_note(row)
        if include_children:
            note.tags = self.get_tags_for_note(note_id)
            note.cards = self.card_repo.list_by_note(note_id)
        return note

    def get_by_uuid(self, note_uuid: str, include_children: bool = True) -> NoteModel | None:
        row = self.conn.execute("SELECT * FROM notes WHERE uuid = ?;", (note_uuid,)).fetchone()
        if not row:
            return None
        note = self._row_to_note(row)
        if include_children and note.id is not None:
            note.tags = self.get_tags_for_note(note.id)
            note.cards = self.card_repo.list_by_note(note.id)
        return note

    def get_by_external_key(self, course_id: int, external_key: str) -> NoteModel | None:
        row = self.conn.execute(
            "SELECT * FROM notes WHERE course_id = ? AND external_key = ?;",
            (course_id, external_key),
        ).fetchone()
        if not row:
            return None
        note = self._row_to_note(row)
        if note.id is not None:
            note.tags = self.get_tags_for_note(note.id)
            note.cards = self.card_repo.list_by_note(note.id)
        return note

    def list_by_course(self, course_id: int, include_children: bool = True) -> list[NoteModel]:
        rows = self.conn.execute(
            """
            SELECT DISTINCT n.id, n.uuid, ? AS course_id, n.external_key,
                   n.title, n.premise_html,
                   CASE WHEN cn.pos_x IS NOT NULL AND (cn.pos_x != 0.0 OR cn.pos_y != 0.0) THEN cn.pos_x ELSE n.pos_x END AS pos_x,
                   CASE WHEN cn.pos_y IS NOT NULL AND (cn.pos_x != 0.0 OR cn.pos_y != 0.0) THEN cn.pos_y ELSE n.pos_y END AS pos_y,
                   n.review_mode, n.desired_retention, COALESCE(cn.is_pinned, n.is_pinned) AS is_pinned,
                   n.created_at, n.updated_at
            FROM notes n
            LEFT JOIN course_notes cn ON cn.note_id = n.id AND cn.course_id = ?
            WHERE cn.course_id = ? OR (n.course_id = ? AND NOT EXISTS (SELECT 1 FROM course_notes cn2 WHERE cn2.note_id = n.id))
            ORDER BY n.id ASC;
            """,
            (course_id, course_id, course_id, course_id),
        ).fetchall()
        notes = [self._row_to_note(r) for r in rows]
        if not include_children or not notes:
            return notes

        note_map = {n.id: n for n in notes if n.id is not None}
        placeholders = ",".join("?" for _ in note_map)
        note_ids = list(note_map.keys())

        tag_rows = self.conn.execute(
            f"""
            SELECT nt.note_id, t.name
            FROM note_tags nt
            JOIN tags t ON t.id = nt.tag_id
            WHERE nt.note_id IN ({placeholders})
            ORDER BY t.name ASC;
            """,
            note_ids,
        ).fetchall()
        for tr in tag_rows:
            nid = int(tr["note_id"])
            if nid in note_map:
                note_map[nid].tags.append(str(tr["name"]))

        card_rows = self.conn.execute(
            f"""
            SELECT c.*, cs.card_id, cs.state, cs.step, cs.stability, cs.difficulty,
                   cs.due_at, cs.last_review_at, cs.reps, cs.lapses,
                   cs.scheduled_days, cs.elapsed_days, cs.is_suspended, cs.is_buried
            FROM cards c
            LEFT JOIN card_schedules cs ON cs.card_id = c.id
            WHERE c.note_id IN ({placeholders})
            ORDER BY c.note_id ASC, c.step_order ASC, c.id ASC;
            """,
            note_ids,
        ).fetchall()
        for cr in card_rows:
            card = CardRepository.row_to_card(cr)
            if card.note_id in note_map:
                note_map[card.note_id].cards.append(card)

        return notes

    def create(self, note: NoteModel) -> NoteModel:
        now = datetime.now(timezone.utc).isoformat()
        note.created_at = note.created_at or now
        note.updated_at = now
        cur = self.conn.execute(
            """
            INSERT INTO notes (
                uuid, course_id, external_key, title, premise_html,
                pos_x, pos_y, review_mode, desired_retention, is_pinned,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                note.uuid,
                note.course_id,
                note.external_key,
                note.title,
                note.premise_html,
                note.pos_x,
                note.pos_y,
                note.review_mode.value,
                note.desired_retention,
                1 if note.is_pinned else 0,
                note.created_at,
                note.updated_at,
            ),
        )
        note.id = int(cur.lastrowid)
        if note.course_id is not None:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO course_notes (course_id, note_id, pos_x, pos_y, is_pinned)
                VALUES (?, ?, ?, ?, ?);
                """,
                (note.course_id, note.id, note.pos_x, note.pos_y, 1 if note.is_pinned else 0),
            )
        if note.tags:
            self.set_tags_for_note(note.id, note.tags)
        for idx, card in enumerate(note.cards):
            card.note_id = note.id
            if card.step_order == 0 and idx > 0:
                card.step_order = idx
            self.card_repo.create(card)
        return note

    def update(self, note: NoteModel, sync_cards: bool = True) -> None:
        if note.id is None:
            raise ValueError("Cannot update NoteModel without id")
        note.updated_at = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """
            UPDATE notes
            SET course_id = ?, external_key = ?, title = ?, premise_html = ?,
                pos_x = ?, pos_y = ?, review_mode = ?, desired_retention = ?,
                is_pinned = ?, updated_at = ?
            WHERE id = ?;
            """,
            (
                note.course_id,
                note.external_key,
                note.title,
                note.premise_html,
                note.pos_x,
                note.pos_y,
                note.review_mode.value,
                note.desired_retention,
                1 if note.is_pinned else 0,
                note.updated_at,
                note.id,
            ),
        )
        self.set_tags_for_note(note.id, note.tags)
        if sync_cards:
            existing_cards = self.card_repo.list_by_note(note.id)
            existing_ids = {c.id for c in existing_cards if c.id is not None}
            incoming_ids = {c.id for c in note.cards if c.id is not None}
            for del_id in existing_ids - incoming_ids:
                self.card_repo.delete(del_id)
            for idx, card in enumerate(note.cards):
                card.note_id = note.id
                card.step_order = idx
                if card.id is not None and card.id in existing_ids:
                    self.card_repo.update(card)
                else:
                    self.card_repo.create(card)

    def update_position(self, note_id: int, pos_x: float, pos_y: float, course_id: int | None = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "UPDATE notes SET pos_x = ?, pos_y = ?, updated_at = ? WHERE id = ?;",
            (pos_x, pos_y, now, note_id),
        )
        if course_id is not None:
            self.conn.execute(
                """
                INSERT INTO course_notes (course_id, note_id, pos_x, pos_y, is_pinned)
                VALUES (?, ?, ?, ?, 0)
                ON CONFLICT (course_id, note_id) DO UPDATE SET pos_x = excluded.pos_x, pos_y = excluded.pos_y;
                """,
                (course_id, note_id, pos_x, pos_y),
            )
        else:
            self.conn.execute(
                """
                UPDATE course_notes
                SET pos_x = ?, pos_y = ?
                WHERE note_id = ?;
                """,
                (pos_x, pos_y, note_id),
            )

    def update_positions_bulk(self, positions: dict[int, tuple[float, float]], course_id: int | None = None) -> None:
        if not positions:
            return
        now = datetime.now(timezone.utc).isoformat()
        params = [(xy[0], xy[1], now, nid) for nid, xy in positions.items()]
        self.conn.executemany(
            "UPDATE notes SET pos_x = ?, pos_y = ?, updated_at = ? WHERE id = ?;",
            params,
        )
        if course_id is not None:
            cn_params = [(course_id, nid, xy[0], xy[1]) for nid, xy in positions.items()]
            self.conn.executemany(
                """
                INSERT INTO course_notes (course_id, note_id, pos_x, pos_y, is_pinned)
                VALUES (?, ?, ?, ?, 0)
                ON CONFLICT (course_id, note_id) DO UPDATE SET pos_x = excluded.pos_x, pos_y = excluded.pos_y;
                """,
                cn_params,
            )
        else:
            fallback_params = [(xy[0], xy[1], nid) for nid, xy in positions.items()]
            self.conn.executemany(
                """
                UPDATE course_notes
                SET pos_x = ?, pos_y = ?
                WHERE note_id = ?;
                """,
                fallback_params,
            )

    def unlink_from_course(self, course_id: int, note_id: int) -> None:
        """Soft-delete: removes note from course DAG (course_notes), preserving the note,
        its flashcards, review schedules, and epistemic edges between notes in the database."""
        self.conn.execute("DELETE FROM course_notes WHERE course_id = ? AND note_id = ?;", (course_id, note_id))
        other = self.conn.execute("SELECT course_id FROM course_notes WHERE note_id = ? LIMIT 1;", (note_id,)).fetchone()
        new_cid = int(other["course_id"]) if other else None
        try:
            self.conn.execute("UPDATE notes SET course_id = ? WHERE id = ?;", (new_cid, note_id))
        except sqlite3.IntegrityError:
            pass

    def inject_into_course(self, course_id: int, note_id: int, pos_x: float = 0.0, pos_y: float = 0.0) -> None:
        """Injects an existing note from anywhere in the database into the specified course."""
        self.conn.execute(
            """
            INSERT OR IGNORE INTO course_notes (course_id, note_id, pos_x, pos_y, is_pinned)
            VALUES (?, ?, ?, ?, 0);
            """,
            (course_id, note_id, pos_x, pos_y),
        )
        self.conn.execute(
            "UPDATE notes SET course_id = ? WHERE id = ? AND course_id IS NULL;",
            (course_id, note_id),
        )

    def list_all_notes(self, include_children: bool = True, limit: int = 5000) -> list[NoteModel]:
        rows = self.conn.execute(
            "SELECT * FROM notes ORDER BY title ASC LIMIT ?;",
            (limit,),
        ).fetchall()
        notes = [self._row_to_note(r) for r in rows]
        if not include_children or not notes:
            return notes
        note_map = {n.id: n for n in notes if n.id is not None}
        placeholders = ",".join("?" for _ in note_map)
        note_ids = list(note_map.keys())

        tag_rows = self.conn.execute(
            f"""
            SELECT nt.note_id, t.name
            FROM note_tags nt
            JOIN tags t ON t.id = nt.tag_id
            WHERE nt.note_id IN ({placeholders})
            ORDER BY t.name ASC;
            """,
            note_ids,
        ).fetchall()
        for tr in tag_rows:
            nid = int(tr["note_id"])
            if nid in note_map:
                note_map[nid].tags.append(str(tr["name"]))

        card_rows = self.conn.execute(
            f"""
            SELECT c.*, cs.card_id, cs.state, cs.step, cs.stability, cs.difficulty,
                   cs.due_at, cs.last_review_at, cs.reps, cs.lapses,
                   cs.scheduled_days, cs.elapsed_days, cs.is_suspended, cs.is_buried
            FROM cards c
            LEFT JOIN card_schedules cs ON cs.card_id = c.id
            WHERE c.note_id IN ({placeholders})
            ORDER BY c.note_id ASC, c.step_order ASC, c.id ASC;
            """,
            note_ids,
        ).fetchall()
        for cr in card_rows:
            card = CardRepository.row_to_card(cr)
            if card.note_id in note_map:
                note_map[card.note_id].cards.append(card)

        return notes

    def delete(self, note_id: int, bridge_edges: bool = False) -> None:
        if bridge_edges:
            note_row = self.conn.execute("SELECT course_id FROM notes WHERE id = ?;", (note_id,)).fetchone()
            if note_row:
                cid = int(note_row["course_id"])
                parents = [
                    int(r["source_note_id"])
                    for r in self.conn.execute("SELECT source_note_id FROM edges WHERE target_note_id = ?;", (note_id,)).fetchall()
                ]
                children = [
                    int(r["target_note_id"])
                    for r in self.conn.execute("SELECT target_note_id FROM edges WHERE source_note_id = ?;", (note_id,)).fetchall()
                ]
                for p in parents:
                    for ch in children:
                        if p != ch:
                            self.create_edge(EdgeModel(course_id=cid, source_note_id=p, target_note_id=ch))
        self.conn.execute("DELETE FROM notes WHERE id = ?;", (note_id,))

    def get_tags_for_note(self, note_id: int) -> list[str]:
        rows = self.conn.execute(
            """
            SELECT t.name
            FROM note_tags nt
            JOIN tags t ON t.id = nt.tag_id
            WHERE nt.note_id = ?
            ORDER BY t.name ASC;
            """,
            (note_id,),
        ).fetchall()
        return [str(r["name"]) for r in rows]

    def ensure_tag(self, name: str, color_hex: str = "#cba6f7") -> int:
        clean = name.strip().lower().replace(" ", "_")
        row = self.conn.execute("SELECT id FROM tags WHERE name = ?;", (clean,)).fetchone()
        if row:
            return int(row["id"])
        cur = self.conn.execute(
            "INSERT INTO tags (name, color_hex) VALUES (?, ?);",
            (clean, color_hex),
        )
        return int(cur.lastrowid)

    def set_tags_for_note(self, note_id: int, tag_names: list[str]) -> None:
        self.conn.execute("DELETE FROM note_tags WHERE note_id = ?;", (note_id,))
        seen: set[str] = set()
        for t in tag_names:
            clean = t.strip().lower().replace(" ", "_")
            if not clean or clean in seen:
                continue
            seen.add(clean)
            tag_id = self.ensure_tag(clean)
            self.conn.execute(
                "INSERT OR IGNORE INTO note_tags (note_id, tag_id) VALUES (?, ?);",
                (note_id, tag_id),
            )

    def add_tag_bulk(self, note_ids: list[int], tag_name: str) -> None:
        if not note_ids:
            return
        tag_id = self.ensure_tag(tag_name)
        self.conn.executemany(
            "INSERT OR IGNORE INTO note_tags (note_id, tag_id) VALUES (?, ?);",
            [(nid, tag_id) for nid in note_ids],
        )

    def remove_tag_bulk(self, note_ids: list[int], tag_name: str) -> None:
        if not note_ids:
            return
        clean = tag_name.strip().lower().replace(" ", "_")
        row = self.conn.execute("SELECT id FROM tags WHERE name = ?;", (clean,)).fetchone()
        if not row:
            return
        tag_id = int(row["id"])
        placeholders = ",".join("?" for _ in note_ids)
        self.conn.execute(
            f"DELETE FROM note_tags WHERE tag_id = ? AND note_id IN ({placeholders});",
            [tag_id, *note_ids],
        )

    def list_all_tags(self, limit: int = 2500) -> list[TagModel]:
        rows = self.conn.execute(
            "SELECT id, name, color_hex FROM tags ORDER BY name ASC LIMIT ?;",
            (limit,),
        ).fetchall()
        return [TagModel(id=int(r["id"]), name=str(r["name"]), color_hex=str(r["color_hex"])) for r in rows]

    # --- Edges ---

    @staticmethod
    def _row_to_edge(row: sqlite3.Row) -> EdgeModel:
        return EdgeModel(
            id=int(row["id"]),
            uuid=str(row["uuid"]),
            course_id=int(row["course_id"]),
            source_note_id=int(row["source_note_id"]),
            target_note_id=int(row["target_note_id"]),
            label=str(row["label"]),
            weight=float(row["weight"]),
            created_at=str(row["created_at"]),
        )

    def list_edges_by_course(self, course_id: int) -> list[EdgeModel]:
        rows = self.conn.execute(
            """
            SELECT e.* FROM edges e
            JOIN course_notes cn_src ON cn_src.note_id = e.source_note_id AND cn_src.course_id = ?
            JOIN course_notes cn_dst ON cn_dst.note_id = e.target_note_id AND cn_dst.course_id = ?
            ORDER BY e.id ASC;
            """,
            (course_id, course_id),
        ).fetchall()
        return [self._row_to_edge(r) for r in rows]

    def create_edge(self, edge: EdgeModel) -> EdgeModel | None:
        if edge.source_note_id == edge.target_note_id:
            return None
        existing = self.conn.execute(
            "SELECT * FROM edges WHERE source_note_id = ? AND target_note_id = ?;",
            (edge.source_note_id, edge.target_note_id),
        ).fetchone()
        if existing:
            return self._row_to_edge(existing)
        now = datetime.now(timezone.utc).isoformat()
        edge.created_at = edge.created_at or now
        cur = self.conn.execute(
            """
            INSERT INTO edges (uuid, course_id, source_note_id, target_note_id, label, weight, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            (
                edge.uuid,
                edge.course_id,
                edge.source_note_id,
                edge.target_note_id,
                edge.label,
                edge.weight,
                edge.created_at,
            ),
        )
        edge.id = int(cur.lastrowid)
        return edge

    def get_edge_between(self, source_note_id: int, target_note_id: int) -> EdgeModel | None:
        row = self.conn.execute(
            "SELECT * FROM edges WHERE source_note_id = ? AND target_note_id = ?;",
            (source_note_id, target_note_id),
        ).fetchone()
        return self._row_to_edge(row) if row else None

    def delete_edge(self, source_note_id: int, target_note_id: int) -> None:
        self.conn.execute(
            "DELETE FROM edges WHERE source_note_id = ? AND target_note_id = ?;",
            (source_note_id, target_note_id),
        )

    def delete_edge_by_id(self, edge_id: int) -> None:
        self.conn.execute("DELETE FROM edges WHERE id = ?;", (edge_id,))

    def get_ancestors_recursive(self, target_note_ids: list[int]) -> list[int]:
        """Returns all prerequisite ancestor note IDs (inclusive) using a recursive CTE."""
        if not target_note_ids:
            return []
        placeholders = ",".join("?" for _ in target_note_ids)
        rows = self.conn.execute(
            f"""
            WITH RECURSIVE prereq_chain(note_id, depth) AS (
                SELECT id, 0 FROM notes WHERE id IN ({placeholders})
                UNION
                SELECT e.source_note_id, pc.depth + 1
                FROM edges e
                JOIN prereq_chain pc ON e.target_note_id = pc.note_id
                WHERE pc.depth < 50
            )
            SELECT DISTINCT note_id FROM prereq_chain;
            """,
            target_note_ids,
        ).fetchall()
        return [int(r["note_id"]) for r in rows]
