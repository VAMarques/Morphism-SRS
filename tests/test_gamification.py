from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from morphism_srs.storage.database import DatabaseManager
from morphism_srs.storage.repositories.gamification_repo import GamificationRepository


class TestGamification(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp_dir.name)
        self.db_path = self.tmp / "test_gamification.db"

        schema_path = (
            Path(__file__).resolve().parent.parent
            / "src"
            / "morphism_srs"
            / "storage"
            / "schema_v2.sql"
        )
        self.db_mgr = DatabaseManager(self.db_path, schema_path)
        self.db_mgr.initialize()
        self.conn = self.db_mgr.connection
        self.repo = GamificationRepository(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        self.temp_dir.cleanup()

    def test_initial_entry(self) -> None:
        now = datetime(2026, 10, 28, 10, 0, 0, tzinfo=timezone.utc)
        streak, xp = self.repo.record_entry(now=now)
        self.assertEqual(streak, 1)
        self.assertEqual(xp, 0.0)

    def test_same_day_window_under_18h(self) -> None:
        day1 = datetime(2026, 10, 28, 10, 0, 0, tzinfo=timezone.utc)
        self.repo.record_entry(now=day1)

        # 6 hours later: streak stays 1
        later = day1 + timedelta(hours=6)
        streak, _ = self.repo.record_entry(now=later)
        self.assertEqual(streak, 1)

    def test_valid_next_day_window_between_18_and_32h(self) -> None:
        day1 = datetime(2026, 10, 28, 10, 0, 0, tzinfo=timezone.utc)
        self.repo.record_entry(now=day1)

        # 22 hours later: falls within [18, 32] hours window -> streak = 2!
        day2 = day1 + timedelta(hours=22)
        streak, _ = self.repo.record_entry(now=day2)
        self.assertEqual(streak, 2)

        # 24 hours after day 2 -> streak = 3!
        day3 = day2 + timedelta(hours=24)
        streak, _ = self.repo.record_entry(now=day3)
        self.assertEqual(streak, 3)

    def test_streak_reset_over_32h(self) -> None:
        day1 = datetime(2026, 10, 28, 10, 0, 0, tzinfo=timezone.utc)
        self.repo.record_entry(now=day1)

        # 35 hours later: more than 32 hours elapsed -> streak resets to 1
        day2 = day1 + timedelta(hours=35)
        streak, _ = self.repo.record_entry(now=day2)
        self.assertEqual(streak, 1)

    def test_xp_accumulation_and_decoupling(self) -> None:
        stats = self.repo.get_stats()
        self.assertEqual(stats["total_xp"], 0.0)

        # Rating 3 reviews adds 3.0 XP
        self.repo.add_review_xp(1.0)
        self.repo.add_review_xp(1.0)
        self.repo.add_review_xp(1.0)

        stats = self.repo.get_stats()
        self.assertAlmostEqual(stats["total_xp"], 3.0)

        # Even if review logs table is cleared or notes deleted, gamification stats persist!
        self.conn.execute("DELETE FROM review_logs;")
        stats = self.repo.get_stats()
        self.assertAlmostEqual(stats["total_xp"], 3.0)


if __name__ == "__main__":
    unittest.main()
