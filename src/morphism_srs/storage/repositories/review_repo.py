from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from morphism_srs.domain.enums import CardState
from morphism_srs.domain.models import CardModel, CardScheduleModel, ReviewLogModel
from morphism_srs.storage.repositories.card_repo import CardRepository


class ReviewRepository:
    """Repository for review_logs, Ctrl+Z undo rollback, and Auto-Study / Custom Study queues."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.card_repo = CardRepository(conn)

    @staticmethod
    def _row_to_log(row: sqlite3.Row) -> ReviewLogModel:
        return ReviewLogModel(
            id=int(row["id"]),
            uuid=str(row["uuid"]),
            card_id=int(row["card_id"]),
            rating=int(row["rating"]),
            reviewed_at=str(row["reviewed_at"]),
            duration_ms=int(row["duration_ms"]),
            prev_state=int(row["prev_state"]),
            prev_step=int(row["prev_step"]) if row["prev_step"] is not None else None,
            prev_stability=float(row["prev_stability"]) if row["prev_stability"] is not None else None,
            prev_difficulty=float(row["prev_difficulty"]) if row["prev_difficulty"] is not None else None,
            prev_due_at=str(row["prev_due_at"]) if row["prev_due_at"] is not None else None,
            prev_last_review_at=str(row["prev_last_review_at"]) if row["prev_last_review_at"] is not None else None,
            new_state=int(row["new_state"]),
            new_step=int(row["new_step"]) if row["new_step"] is not None else None,
            new_stability=float(row["new_stability"]) if row["new_stability"] is not None else None,
            new_difficulty=float(row["new_difficulty"]) if row["new_difficulty"] is not None else None,
            new_due_at=str(row["new_due_at"]),
            elapsed_days=float(row["elapsed_days"]),
            scheduled_days=float(row["scheduled_days"]),
        )

    def record_review(self, new_schedule: CardScheduleModel, log: ReviewLogModel) -> ReviewLogModel:
        """Persists updated schedule and inserts the delta review_log row."""
        self.card_repo.update_schedule(new_schedule)
        cur = self.conn.execute(
            """
            INSERT INTO review_logs (
                uuid, card_id, rating, reviewed_at, duration_ms,
                prev_state, prev_step, prev_stability, prev_difficulty, prev_due_at, prev_last_review_at,
                new_state, new_step, new_stability, new_difficulty, new_due_at,
                elapsed_days, scheduled_days
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                log.uuid,
                log.card_id,
                log.rating,
                log.reviewed_at,
                log.duration_ms,
                log.prev_state,
                log.prev_step,
                log.prev_stability,
                log.prev_difficulty,
                log.prev_due_at,
                log.prev_last_review_at,
                log.new_state,
                log.new_step,
                log.new_stability,
                log.new_difficulty,
                log.new_due_at,
                log.elapsed_days,
                log.scheduled_days,
            ),
        )
        log.id = int(cur.lastrowid)
        return log

    def undo_review(self, log_id: int) -> CardScheduleModel | None:
        """Restores exact previous card_schedules state from review_logs(log_id) and deletes the log."""
        row = self.conn.execute("SELECT * FROM review_logs WHERE id = ?;", (log_id,)).fetchone()
        if not row:
            return None
        log = self._row_to_log(row)
        cur_sched_row = self.conn.execute(
            "SELECT * FROM card_schedules WHERE card_id = ?;",
            (log.card_id,),
        ).fetchone()
        if not cur_sched_row:
            return None

        cur_reps = max(0, int(cur_sched_row["reps"]) - 1)
        was_lapse = log.rating == 1 and log.prev_state == int(CardState.REVIEW)
        cur_lapses = max(0, int(cur_sched_row["lapses"]) - (1 if was_lapse else 0))

        restored = CardScheduleModel(
            card_id=log.card_id,
            state=CardState(log.prev_state),
            step=log.prev_step,
            stability=log.prev_stability,
            difficulty=log.prev_difficulty,
            due_at=log.prev_due_at or datetime.now(timezone.utc).isoformat(),
            last_review_at=log.prev_last_review_at,
            reps=cur_reps,
            lapses=cur_lapses,
            scheduled_days=int(cur_sched_row["scheduled_days"]),
            elapsed_days=int(cur_sched_row["elapsed_days"]),
            is_suspended=bool(cur_sched_row["is_suspended"]),
            is_buried=bool(cur_sched_row["is_buried"]),
        )
        self.card_repo.update_schedule(restored)
        self.conn.execute("DELETE FROM review_logs WHERE id = ?;", (log_id,))
        return restored

    def list_logs_for_card(self, card_id: int) -> list[ReviewLogModel]:
        rows = self.conn.execute(
            "SELECT * FROM review_logs WHERE card_id = ? ORDER BY reviewed_at ASC, id ASC;",
            (card_id,),
        ).fetchall()
        return [self._row_to_log(r) for r in rows]

    def fetch_study_candidates(
        self,
        course_ids: list[int] | None = None,
        note_ids: list[int] | None = None,
        tags: list[str] | None = None,
        only_due_or_new: bool = True,
        ahead_days: int = 0,
        failed_within_days: int | None = None,
        now_iso: str | None = None,
    ) -> list[CardModel]:
        """Fetches candidate cards with schedules for Auto-Study or Custom Study."""
        now_dt = datetime.fromisoformat((now_iso or datetime.now(timezone.utc).isoformat()).replace("Z", "+00:00"))
        cutoff_iso = (now_dt + timedelta(days=max(0, ahead_days))).isoformat()

        clauses = ["cs.is_suspended = 0", "cs.is_buried = 0"]
        params: list[Any] = []

        if course_ids:
            ph = ",".join("?" for _ in course_ids)
            clauses.append(f"n.course_id IN ({ph})")
            params.extend(course_ids)

        if note_ids:
            ph = ",".join("?" for _ in note_ids)
            clauses.append(f"c.note_id IN ({ph})")
            params.extend(note_ids)

        if tags:
            clean_tags = [t.strip().lower() for t in tags if t.strip()]
            if clean_tags:
                ph = ",".join("?" for _ in clean_tags)
                clauses.append(
                    f"""
                    EXISTS (
                        SELECT 1 FROM note_tags nt
                        JOIN tags tg ON tg.id = nt.tag_id
                        WHERE nt.note_id = n.id AND tg.name IN ({ph})
                    )
                    """
                )
                params.extend(clean_tags)

        if only_due_or_new:
            learn_ahead_iso = (now_dt + timedelta(minutes=20) + timedelta(days=max(0, ahead_days))).isoformat()
            clauses.append("(cs.state = 0 OR (cs.state IN (1, 3) AND cs.due_at <= ?) OR cs.due_at <= ?)")
            params.extend([learn_ahead_iso, cutoff_iso])

        if failed_within_days is not None and failed_within_days > 0:
            since_iso = (now_dt - timedelta(days=failed_within_days)).isoformat()
            clauses.append(
                """
                EXISTS (
                    SELECT 1 FROM review_logs rl
                    WHERE rl.card_id = c.id AND rl.rating = 1 AND rl.reviewed_at >= ?
                )
                """
            )
            params.append(since_iso)

        where_sql = " AND ".join(clauses)
        rows = self.conn.execute(
            f"""
            SELECT c.*, cs.card_id, cs.state, cs.step, cs.stability, cs.difficulty,
                   cs.due_at, cs.last_review_at, cs.reps, cs.lapses,
                   cs.scheduled_days, cs.elapsed_days, cs.is_suspended, cs.is_buried
            FROM cards c
            JOIN notes n ON n.id = c.note_id
            JOIN card_schedules cs ON cs.card_id = c.id
            WHERE {where_sql}
            ORDER BY cs.due_at ASC, c.note_id ASC, c.step_order ASC;
            """,
            params,
        ).fetchall()
        return [CardRepository.row_to_card(r) for r in rows]

    def get_daily_review_counts(self, days: int = 365) -> dict[str, int]:
        """Returns {'YYYY-MM-DD': count} for the heatmap chart."""
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rows = self.conn.execute(
            """
            SELECT substr(reviewed_at, 1, 10) AS day_str, COUNT(*) AS cnt
            FROM review_logs
            WHERE reviewed_at >= ?
            GROUP BY day_str
            ORDER BY day_str ASC;
            """,
            (since,),
        ).fetchall()
        return {str(r["day_str"]): int(r["cnt"]) for r in rows if r["day_str"]}

    def get_rating_distribution(self, course_id: int | None = None) -> dict[int, int]:
        if course_id is None:
            rows = self.conn.execute(
                "SELECT rating, COUNT(*) AS cnt FROM review_logs GROUP BY rating;"
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT rl.rating, COUNT(*) AS cnt
                FROM review_logs rl
                JOIN cards c ON c.id = rl.card_id
                JOIN notes n ON n.id = c.note_id
                WHERE n.course_id = ?
                GROUP BY rl.rating;
                """,
                (course_id,),
            ).fetchall()
        dist = {1: 0, 2: 0, 3: 0, 4: 0}
        for r in rows:
            dist[int(r["rating"])] = int(r["cnt"])
        return dist

    def get_future_due_forecast(self, days: int = 30, course_id: int | None = None) -> dict[str, int]:
        now = datetime.now(timezone.utc)
        end = (now + timedelta(days=days)).isoformat()
        if course_id is None:
            rows = self.conn.execute(
                """
                SELECT substr(due_at, 1, 10) AS day_str, COUNT(*) AS cnt
                FROM card_schedules
                WHERE is_suspended = 0 AND state > 0 AND due_at <= ?
                GROUP BY day_str
                ORDER BY day_str ASC;
                """,
                (end,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT substr(cs.due_at, 1, 10) AS day_str, COUNT(*) AS cnt
                FROM card_schedules cs
                JOIN cards c ON c.id = cs.card_id
                JOIN notes n ON n.id = c.note_id
                WHERE n.course_id = ? AND cs.is_suspended = 0 AND cs.state > 0 AND cs.due_at <= ?
                GROUP BY day_str
                ORDER BY day_str ASC;
                """,
                (course_id, end),
            ).fetchall()
        return {str(r["day_str"]): int(r["cnt"]) for r in rows if r["day_str"]}
