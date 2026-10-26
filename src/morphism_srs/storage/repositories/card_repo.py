from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from morphism_srs.domain.enums import CardState
from morphism_srs.domain.models import CardModel, CardScheduleModel


class CardRepository:
    """Repository for cards and card_schedules."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    @staticmethod
    def row_to_schedule(row: sqlite3.Row) -> CardScheduleModel:
        return CardScheduleModel(
            card_id=int(row["card_id"]),
            state=CardState(int(row["state"])),
            step=int(row["step"]) if row["step"] is not None else None,
            stability=float(row["stability"]) if row["stability"] is not None else None,
            difficulty=float(row["difficulty"]) if row["difficulty"] is not None else None,
            due_at=str(row["due_at"]),
            last_review_at=str(row["last_review_at"]) if row["last_review_at"] is not None else None,
            reps=int(row["reps"]),
            lapses=int(row["lapses"]),
            scheduled_days=int(row["scheduled_days"]),
            elapsed_days=int(row["elapsed_days"]),
            is_suspended=bool(row["is_suspended"]),
            is_buried=bool(row["is_buried"]),
        )

    @classmethod
    def row_to_card(cls, row: sqlite3.Row) -> CardModel:
        sched = None
        if "card_id" in row.keys() and row["card_id"] is not None:
            sched = cls.row_to_schedule(row)
        return CardModel(
            id=int(row["id"]),
            uuid=str(row["uuid"]),
            note_id=int(row["note_id"]),
            step_order=int(row["step_order"]),
            title=str(row["title"]),
            front_html=str(row["front_html"]),
            back_html=str(row["back_html"]),
            hint_html=str(row["hint_html"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            schedule=sched,
        )

    def get_by_id(self, card_id: int) -> CardModel | None:
        row = self.conn.execute(
            """
            SELECT c.*, cs.card_id, cs.state, cs.step, cs.stability, cs.difficulty,
                   cs.due_at, cs.last_review_at, cs.reps, cs.lapses,
                   cs.scheduled_days, cs.elapsed_days, cs.is_suspended, cs.is_buried
            FROM cards c
            LEFT JOIN card_schedules cs ON cs.card_id = c.id
            WHERE c.id = ?;
            """,
            (card_id,),
        ).fetchone()
        return self.row_to_card(row) if row else None

    def get_by_uuid(self, card_uuid: str) -> CardModel | None:
        row = self.conn.execute(
            """
            SELECT c.*, cs.card_id, cs.state, cs.step, cs.stability, cs.difficulty,
                   cs.due_at, cs.last_review_at, cs.reps, cs.lapses,
                   cs.scheduled_days, cs.elapsed_days, cs.is_suspended, cs.is_buried
            FROM cards c
            LEFT JOIN card_schedules cs ON cs.card_id = c.id
            WHERE c.uuid = ?;
            """,
            (card_uuid,),
        ).fetchone()
        return self.row_to_card(row) if row else None

    def list_by_note(self, note_id: int) -> list[CardModel]:
        rows = self.conn.execute(
            """
            SELECT c.*, cs.card_id, cs.state, cs.step, cs.stability, cs.difficulty,
                   cs.due_at, cs.last_review_at, cs.reps, cs.lapses,
                   cs.scheduled_days, cs.elapsed_days, cs.is_suspended, cs.is_buried
            FROM cards c
            LEFT JOIN card_schedules cs ON cs.card_id = c.id
            WHERE c.note_id = ?
            ORDER BY c.step_order ASC, c.id ASC;
            """,
            (note_id,),
        ).fetchall()
        return [self.row_to_card(r) for r in rows]

    def create(self, card: CardModel) -> CardModel:
        now = datetime.now(timezone.utc).isoformat()
        card.created_at = card.created_at or now
        card.updated_at = now
        cur = self.conn.execute(
            """
            INSERT INTO cards (uuid, note_id, step_order, title, front_html, back_html, hint_html, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                card.uuid,
                card.note_id,
                card.step_order,
                card.title,
                card.front_html,
                card.back_html,
                card.hint_html,
                card.created_at,
                card.updated_at,
            ),
        )
        card.id = int(cur.lastrowid)
        if card.schedule is not None:
            card.schedule.card_id = card.id
            self.update_schedule(card.schedule)
        else:
            loaded = self.get_by_id(card.id)
            if loaded:
                card.schedule = loaded.schedule
        return card

    def update(self, card: CardModel) -> None:
        card.updated_at = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """
            UPDATE cards
            SET step_order = ?, title = ?, front_html = ?, back_html = ?, hint_html = ?, updated_at = ?
            WHERE id = ?;
            """,
            (
                card.step_order,
                card.title,
                card.front_html,
                card.back_html,
                card.hint_html,
                card.updated_at,
                card.id,
            ),
        )
        if card.schedule is not None and card.id is not None:
            card.schedule.card_id = card.id
            self.update_schedule(card.schedule)

    def update_schedule(self, sched: CardScheduleModel) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO card_schedules (
                card_id, state, step, stability, difficulty, due_at, last_review_at,
                reps, lapses, scheduled_days, elapsed_days, is_suspended, is_buried
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                sched.card_id,
                int(sched.state),
                sched.step,
                sched.stability,
                sched.difficulty,
                sched.due_at,
                sched.last_review_at,
                sched.reps,
                sched.lapses,
                sched.scheduled_days,
                sched.elapsed_days,
                1 if sched.is_suspended else 0,
                1 if sched.is_buried else 0,
            ),
        )

    def delete(self, card_id: int) -> None:
        self.conn.execute("DELETE FROM cards WHERE id = ?;", (card_id,))

    def set_suspended_bulk(self, card_ids: list[int], suspended: bool) -> None:
        if not card_ids:
            return
        placeholders = ",".join("?" for _ in card_ids)
        self.conn.execute(
            f"UPDATE card_schedules SET is_suspended = ? WHERE card_id IN ({placeholders});",
            [1 if suspended else 0, *card_ids],
        )

    def reset_schedules_bulk(self, card_ids: list[int]) -> None:
        if not card_ids:
            return
        now = datetime.now(timezone.utc).isoformat()
        placeholders = ",".join("?" for _ in card_ids)
        self.conn.execute(
            f"""
            UPDATE card_schedules
            SET state = 0, step = 0, stability = NULL, difficulty = NULL,
                due_at = ?, last_review_at = NULL, reps = 0, lapses = 0,
                scheduled_days = 0, elapsed_days = 0
            WHERE card_id IN ({placeholders});
            """,
            [now, *card_ids],
        )
