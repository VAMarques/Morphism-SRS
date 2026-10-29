from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from morphism_srs.domain.scheduler_engine import parse_utc


class GamificationRepository:
    """Manages independent, persistent streak and XP tracking decoupled from deck reviews."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self._ensure_table()

    def _ensure_table(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS gamification_stats (
                id                  INTEGER PRIMARY KEY CHECK (id = 1),
                streak_count        INTEGER NOT NULL DEFAULT 0,
                total_xp            REAL NOT NULL DEFAULT 0.0,
                last_login_at       TEXT,
                updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            ) STRICT;
            """
        )
        self.conn.execute(
            "INSERT OR IGNORE INTO gamification_stats (id, streak_count, total_xp, last_login_at) VALUES (1, 0, 0.0, NULL);"
        )

    def record_entry(self, now: datetime | None = None) -> tuple[int, float]:
        """
        Updates the streak on user entrance:
        - If first login: streak becomes 1.
        - If elapsed time is < 18 hours: same day/session window, streak stays the same.
        - If elapsed time is between 18 and 32 hours: streak increments by 1.
        - If elapsed time is > 32 hours: grace period expired, streak resets to 1.
        Returns: (streak_count, total_xp)
        """
        now_dt = now or datetime.now(timezone.utc)
        now_str = now_dt.isoformat()

        row = self.conn.execute(
            "SELECT streak_count, total_xp, last_login_at FROM gamification_stats WHERE id = 1;"
        ).fetchone()

        if not row:
            self._ensure_table()
            row = self.conn.execute(
                "SELECT streak_count, total_xp, last_login_at FROM gamification_stats WHERE id = 1;"
            ).fetchone()

        current_streak = int(row["streak_count"]) if row else 0
        total_xp = float(row["total_xp"]) if row else 0.0
        last_login_raw = row["last_login_at"] if row else None

        if not last_login_raw:
            new_streak = 1
            new_login_at = now_str
        else:
            try:
                last_dt = parse_utc(last_login_raw)
                elapsed_hours = (now_dt - last_dt).total_seconds() / 3600.0
            except Exception:
                elapsed_hours = 999.0

            if elapsed_hours < 18.0:
                # Within the active study day window, maintain streak
                new_streak = max(1, current_streak)
                new_login_at = last_login_raw
            elif 18.0 <= elapsed_hours <= 32.0:
                # Next day arrived within valid 18-32h window: increment streak!
                new_streak = current_streak + 1
                new_login_at = now_str
            else:
                # Elapsed > 32 hours: streak reset
                new_streak = 1
                new_login_at = now_str

        self.conn.execute(
            """
            UPDATE gamification_stats
            SET streak_count = ?, last_login_at = ?, updated_at = ?
            WHERE id = 1;
            """,
            (new_streak, new_login_at, now_str),
        )
        return new_streak, total_xp

    def add_review_xp(self, amount: float = 1.0) -> float:
        """Increments XP by 1.0 per review (regardless of rating) and persists it."""
        now_str = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """
            UPDATE gamification_stats
            SET total_xp = total_xp + ?, updated_at = ?
            WHERE id = 1;
            """,
            (float(amount), now_str),
        )
        row = self.conn.execute("SELECT total_xp FROM gamification_stats WHERE id = 1;").fetchone()
        return float(row["total_xp"]) if row else 0.0

    def get_stats(self) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT streak_count, total_xp, last_login_at, updated_at FROM gamification_stats WHERE id = 1;"
        ).fetchone()
        if not row:
            return {"streak_count": 0, "total_xp": 0.0, "last_login_at": None}
        return {
            "streak_count": int(row["streak_count"]),
            "total_xp": float(row["total_xp"]),
            "last_login_at": row["last_login_at"],
        }
