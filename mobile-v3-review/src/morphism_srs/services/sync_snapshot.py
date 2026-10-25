"""Portable SQLite snapshots; deliberately exclude desktop FTS and private metadata."""
import gzip
import json
from pathlib import Path
import sqlite3
import tempfile

from morphism_srs.services.delta_sync import TABLE_KEYS, database_uuid


def snapshot(conn, profile_id, profile_name):
    database_uuid(conn)
    with tempfile.TemporaryDirectory(prefix="morphism-snapshot-") as directory:
        path = Path(directory) / "portable.db"
        target = sqlite3.connect(path)
        conn.execute("BEGIN")
        try:
            for table in (*TABLE_KEYS, "app_meta", "sync_oplog"):
                sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()[0]
                target.execute(sql.replace(") STRICT", ")"))
            for table in TABLE_KEYS:
                cursor = conn.execute(f"SELECT * FROM {table}")
                target.executemany(f"INSERT INTO {table} VALUES ({','.join('?' for _ in cursor.description)})", cursor)
            seq = conn.execute("SELECT coalesce(max(id),0) FROM sync_oplog").fetchone()[0]
            config = conn.execute("SELECT value_json FROM app_meta WHERE key='global_fsrs_weights'").fetchone()
            meta = {"sync_pc_db_uuid": database_uuid(conn), "sync_last_pc_seq": seq,
                    "sync_profile_id": profile_id, "sync_profile_name": profile_name,
                    "sync_snapshot_version": 3, "global_fsrs_weights": json.loads(config[0]) if config else None}
            target.executemany("INSERT INTO app_meta VALUES (?,?)", ((k, json.dumps(v)) for k, v in meta.items()))
            # Repair imported cards without schedules, also used by the native queue.
            target.execute("INSERT OR IGNORE INTO card_schedules(card_id) SELECT id FROM cards")
            target.execute("CREATE TABLE portable_outbox(seq INTEGER PRIMARY KEY AUTOINCREMENT, log_uuid TEXT UNIQUE NOT NULL)")
            target.execute("CREATE TABLE portable_undo(uuid TEXT PRIMARY KEY, schedule_json TEXT NOT NULL, card_uuid TEXT NOT NULL)")
            target.execute("CREATE TABLE portable_undone(uuid TEXT PRIMARY KEY)")
            for row in conn.execute("SELECT tbl_name,sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"):
                if row[0] in TABLE_KEYS:
                    target.execute(row[1])
            target.execute("PRAGMA user_version=1")
            if target.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("Snapshot contains invalid references")
            target.commit()
        finally:
            conn.execute("ROLLBACK")
            target.close()
        return gzip.compress(path.read_bytes(), mtime=0)
