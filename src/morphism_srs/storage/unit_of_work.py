from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from types import TracebackType
from typing import Any


class UnitOfWork:
    """Context manager wrapping atomic SQLite transactions and sync_oplog recording."""

    def __init__(self, conn: sqlite3.Connection, device_id: str = "desktop-local") -> None:
        self.conn = conn
        self.device_id = device_id
        self._in_tx = False

    def __enter__(self) -> UnitOfWork:
        if not self.conn.in_transaction:
            self.conn.execute("BEGIN IMMEDIATE;")
            self._in_tx = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            if self.conn.in_transaction:
                self.conn.execute("ROLLBACK;")
        else:
            if self._in_tx and self.conn.in_transaction:
                self.conn.execute("COMMIT;")
        self._in_tx = False

    def log_operation(
        self,
        entity_table: str,
        entity_uuid: str,
        operation: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        payload_str = json.dumps(payload or {}, ensure_ascii=False)
        self.conn.execute(
            """
            INSERT INTO sync_oplog (entity_table, entity_uuid, operation, payload_json, created_at, device_id)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (entity_table, entity_uuid, operation, payload_str, now_iso, self.device_id),
        )
