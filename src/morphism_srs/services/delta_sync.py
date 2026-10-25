"""SQLite delta protocol. IDs in pull payloads belong to the paired PC database."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import json
import sqlite3
from uuid import uuid4

from morphism_srs.domain.enums import CardState
from morphism_srs.domain.models import CardScheduleModel, ReviewLogModel
from morphism_srs.domain.scheduler_engine import SchedulerEngine, parse_utc
from morphism_srs.storage.repositories.card_repo import CardRepository
from morphism_srs.storage.repositories.review_repo import ReviewRepository
from morphism_srs.storage.repositories.folder_repo import FolderRepository

# Dependency order, also used by the Android client. Tombstones carry primary keys
# captured by triggers, so cascading deletes never depend on a surviving parent.
TABLE_KEYS = {
    "course_folders": ("id",), "courses": ("id",), "notes": ("id",),
    "course_notes": ("course_id", "note_id"), "cards": ("id",),
    "card_schedules": ("card_id",), "edges": ("id",), "tags": ("id",),
    "note_tags": ("note_id", "tag_id"), "review_logs": ("id",),
    "media_assets": ("sha256_hash",), "scratchbook_pages": ("id",),
}


@contextmanager
def sync_connection(source):
    """Use an independent connection: HTTP threads must not join a UI transaction."""
    path = source.execute("PRAGMA database_list").fetchone()[2]
    conn = sqlite3.connect(path, isolation_level=None, timeout=15) if path else source
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        if conn is not source:
            conn.close()


def database_uuid(conn):
    existing = conn.execute("SELECT value_json FROM app_meta WHERE key='sync_db_uuid'").fetchone()
    if existing:
        return json.loads(existing[0])
    conn.execute("INSERT OR IGNORE INTO app_meta VALUES ('sync_db_uuid', ?)",
                 (json.dumps(str(uuid4())),))
    return json.loads(conn.execute("SELECT value_json FROM app_meta WHERE key='sync_db_uuid'").fetchone()[0])


def pull_delta(conn, since_seq: int):
    if since_seq < 0:
        raise ValueError("since_seq must be nonnegative")
    db_uuid = database_uuid(conn)
    conn.execute("BEGIN")
    try:
        current = conn.execute("SELECT coalesce(max(id),0) FROM sync_oplog").fetchone()[0]
        if since_seq > current:
            raise ValueError("Cursor ahead of PC database; pair again")
        result = {"db_uuid": db_uuid, "current_seq": current, "protocol": 2}
        config = conn.execute("SELECT value_json FROM app_meta WHERE key='global_fsrs_weights'").fetchone()
        result["global_fsrs_weights"] = json.loads(config[0]) if config else None
        if since_seq == 0:
            result.update(mode="bootstrap", tables={
                table: [dict(r) for r in conn.execute(f"SELECT * FROM {table}")]
                for table in TABLE_KEYS
            })
        else:
            changes = {}
            for row in conn.execute("SELECT * FROM sync_oplog WHERE id>? AND id<=? ORDER BY id", (since_seq, current)):
                table = row["entity_table"]
                if table in TABLE_KEYS:
                    key = json.loads(row["payload_json"])
                    # Older releases also wrote descriptive (non-key) entries.
                    # The automatic SQL trigger records the same change completely.
                    if not all(k in key for k in TABLE_KEYS[table]):
                        continue
                    changes[(table, tuple(key[k] for k in TABLE_KEYS[table]))] = key
            upserts = {t: [] for t in TABLE_KEYS}
            deletes = {t: [] for t in TABLE_KEYS}
            for (table, values), key in changes.items():
                where = " AND ".join(f"{k}=?" for k in TABLE_KEYS[table])
                row = conn.execute(f"SELECT * FROM {table} WHERE {where}", values).fetchone()
                (upserts[table] if row else deletes[table]).append(dict(row) if row else key)
            result.update(mode="delta", upserts=upserts, deletes=deletes)
        result["media_manifest"] = [dict(r) for r in conn.execute("SELECT * FROM media_assets")]
        conn.execute("COMMIT")
        return result
    except Exception:
        conn.execute("ROLLBACK")
        raise


def push_delta(conn, payload):
    """Idempotent UUID ingestion and deterministic chronological FSRS reconciliation.

    Replaying authoritative logs also validates mobile schedules instead of trusting
    arbitrary state supplied by a client. Retry after a lost response is harmless.
    """
    if payload.get("db_uuid") != database_uuid(conn):
        raise ValueError("Paired PC database UUID does not match")
    logs = payload.get("new_review_logs", [])
    undone = payload.get("undone_log_uuids", [])
    if not isinstance(logs, list) or not isinstance(undone, list) or len(logs) > 100000:
        raise ValueError("Invalid review batch")
    cards = CardRepository(conn)
    reviews = ReviewRepository(conn)
    affected = set()
    accepted = 0
    max_local = 0
    log_ids = {}
    prior = {}
    def capture(card_id):
        if card_id not in prior:
            prior[card_id] = (cards.get_by_id(card_id).schedule, reviews.list_logs_for_card(card_id))
    conn.execute("BEGIN IMMEDIATE")
    try:
        # Persist tombstones so undo wins even if a delayed push is retried later.
        for log_uuid in undone:
            key = "sync_undo:" + str(log_uuid)
            conn.execute("INSERT OR IGNORE INTO app_meta VALUES (?, 'true')", (key,))
            row = conn.execute("SELECT card_id FROM review_logs WHERE uuid=?", (log_uuid,)).fetchone()
            if row:
                capture(row[0])
                affected.add(row[0])
                conn.execute("DELETE FROM review_logs WHERE uuid=?", (log_uuid,))
        fields = set(ReviewLogModel.__dataclass_fields__) - {"id", "card_id"}
        for item in logs:
            max_local = max(max_local, int(item.get("local_id", item.get("id", 0))))
            if not item.get("uuid") or not item.get("card_uuid"):
                raise ValueError("Review UUID and card_uuid are required")
            reviewed = datetime.fromisoformat(item["reviewed_at"].replace("Z", "+00:00"))
            if reviewed.tzinfo is None:
                raise ValueError("Review timestamp must include a timezone")
            if int(item["rating"]) not in (1, 2, 3, 4) or int(item.get("duration_ms", 0)) < 0:
                raise ValueError("Invalid rating or duration")
            if conn.execute("SELECT 1 FROM app_meta WHERE key=?", ("sync_undo:" + item["uuid"],)).fetchone():
                continue
            existing = conn.execute("SELECT card_id,rating,reviewed_at,id FROM review_logs WHERE uuid=?", (item["uuid"],)).fetchone()
            card = cards.get_by_uuid(item["card_uuid"])
            if not card:  # Deleted on PC: acknowledge stale reviews without resurrecting content.
                continue
            if existing:
                if tuple(existing)[:3] != (card.id, int(item["rating"]), item["reviewed_at"]):
                    raise ValueError("Review UUID reused with different content")
                log_ids[item["uuid"]] = existing["id"]
                continue
            log = ReviewLogModel(card_id=card.id, **{k: item[k] for k in fields if k in item})
            capture(card.id)
            values = asdict(log)
            values.pop("id")
            names = list(values)
            cursor = conn.execute(f"INSERT INTO review_logs ({','.join(names)}) VALUES ({','.join('?' for _ in names)})", tuple(values.values()))
            log_ids[item["uuid"]] = cursor.lastrowid
            affected.add(card.id)
            accepted += 1
        for card_id in affected:
            card = cards.get_by_id(card_id)
            config = conn.execute("""SELECT coalesce(n.desired_retention,c.desired_retention,0.8),c.folder_id
                FROM notes n LEFT JOIN courses c ON c.id=n.course_id
                LEFT JOIN course_folders f ON f.id=c.folder_id WHERE n.id=?""", (card.note_id,)).fetchone()
            weights = FolderRepository(conn).resolve_effective_fsrs_weights(config[1])
            engine = SchedulerEngine(desired_retention=config[0], weights_json=weights)
            history = reviews.list_logs_for_card(card_id)
            previous, old_history = prior[card_id]
            # Imported schedules can legitimately predate the available history.
            # Preserve that baseline rather than silently resetting their memory.
            known = old_history + history
            first = min(known, key=lambda lg: (parse_utc(lg.reviewed_at), lg.uuid))
            initial = CardScheduleModel(
                card_id=card_id, state=CardState(first.prev_state), step=first.prev_step,
                stability=first.prev_stability, difficulty=first.prev_difficulty,
                due_at=first.prev_due_at or card.created_at, last_review_at=first.prev_last_review_at,
                reps=max(0, previous.reps - len(old_history)),
                lapses=max(0, previous.lapses - sum(lg.rating == 1 and lg.prev_state == 2 for lg in old_history)),
                scheduled_days=max(0, round((parse_utc(first.prev_due_at)-parse_utc(first.prev_last_review_at)).total_seconds()/86400)) if first.prev_last_review_at and first.prev_due_at else 0,
                is_suspended=previous.is_suspended, is_buried=previous.is_buried,
            )
            schedule = engine.reschedule_from_logs(card_id, history, card.schedule, initial_schedule=initial)
            cards.update_schedule(schedule)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return {"ok": True, "pushed_logs_accepted": accepted, "max_local_log_id": max_local, "log_ids": log_ids}
