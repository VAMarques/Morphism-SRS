from __future__ import annotations

from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import socket
import sqlite3
import threading
import getpass
import time
from urllib.parse import parse_qs, urlparse, urlencode
from cryptography.exceptions import InvalidTag
from morphism_srs.services.sync_crypto import seal, open_sealed, encode, decode
from morphism_srs.services.sync_snapshot import snapshot

from morphism_srs.controllers.event_bus import EventBus
from morphism_srs.controllers.review_controller import ReviewController
from morphism_srs.domain.enums import RatingEnum
from morphism_srs.storage.media_vault import MediaVault
from morphism_srs.storage.unit_of_work import UnitOfWork
from morphism_srs.services.delta_sync import sync_connection, pull_delta, push_delta, database_uuid


def get_lan_ip() -> str:
    """Best-effort discovery of local IPv4 address on the LAN."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def _fetch_table_dicts(conn: sqlite3.Connection, query: str, params: tuple = ()) -> list[dict]:
    cursor = conn.execute(query, params)
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


class EphemeralMobileServer:
    """
    Ephemeral LAN sync authenticated by a QR-shared AES-256 key.
    Legacy plaintext routes require an explicit compatibility opt-in.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        review_controller: ReviewController,
        media_vault: MediaVault,
        event_bus: EventBus,
        mathjax_js_bytes: bytes = b"",
        allow_legacy: bool = False,
    ) -> None:
        self.conn = conn
        self.review_controller = review_controller
        self.media_vault = media_vault
        self.event_bus = event_bus
        self.mathjax_js_bytes = mathjax_js_bytes
        self.token = secrets.token_urlsafe(16)
        self.allow_legacy = allow_legacy
        self.session_key = secrets.token_bytes(32)
        self._seen_requests = set()
        self._expires = time.monotonic() + 1800
        self.db_uuid = database_uuid(conn)
        self.profile_id = self.db_uuid
        row = conn.execute("SELECT value_json FROM app_meta WHERE key='sync_profile_name'").fetchone()
        self.profile_name = json.loads(row[0]) if row else getpass.getuser()
        self.port: int = 0
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> str:
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def _check_token(self) -> bool:
                self.secure = self.path.startswith("/api/v3/") or self.path.startswith("/media/") and bool(self.headers.get("X-Morphism-Auth"))
                if self.secure:
                    try:
                        path = urlparse(self.path).path
                        allowed = {"GET": {"/api/v3/sync/ping", "/api/v3/sync/pull_delta", "/api/v3/sync/snapshot"},
                                   "POST": {"/api/v3/sync/push_delta"}}
                        if path not in allowed.get(self.command, set()) and not (self.command == "GET" and path.startswith("/media/")):
                            return False
                        auth = self.headers.get("X-Morphism-Auth", "")
                        self.aad = f"{self.command} {self.path}".encode()
                        proof = decode(auth)
                        if open_sealed(parent.session_key, proof, self.aad) != b"":
                            return False
                        with parent._lock:
                            if time.monotonic() > parent._expires or auth in parent._seen_requests or len(parent._seen_requests) >= 100000:
                                return False
                            parent._seen_requests.add(auth)
                        self.request_proof = proof
                        self.response_aad = self.aad + b" response " + proof
                        return True
                    except (ValueError, InvalidTag):
                        return False
                if not parent.allow_legacy:
                    return False
                parsed = urlparse(self.path)
                params = parse_qs(parsed.query)
                token_param = params.get("token", [""])[0]
                header_token = self.headers.get("X-Morphism-Token", "")
                return secrets.compare_digest(token_param, parent.token) or secrets.compare_digest(header_token, parent.token)

            def _send_json(self, data: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
                body = json.dumps(data, ensure_ascii=False).encode("utf-8")
                self._send_bytes(body, "application/json; charset=utf-8", status)

            def _send_bytes(self, body, content_type, status=HTTPStatus.OK):
                if self.secure:
                    body = seal(parent.session_key, body, self.response_aad)
                    content_type = "application/vnd.morphism.encrypted"
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.end_headers()
                self.wfile.write(body)

            def do_OPTIONS(self) -> None:
                self.send_response(HTTPStatus.NO_CONTENT)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.end_headers()

            def do_GET(self) -> None:
                if not self._check_token():
                    self.send_error(HTTPStatus.FORBIDDEN, "Invalid or missing sync token")
                    return

                parsed = urlparse(self.path)
                path = parsed.path.rstrip("/")
                path = path.replace("/api/v3/", "/api/v2/", 1)

                if path == "/api/v2/sync/snapshot":
                    with parent._lock, sync_connection(parent.conn) as conn:
                        body = snapshot(conn, parent.profile_id, parent.profile_name)
                    self._send_bytes(body, "application/gzip")
                    return

                if path == "/api/v2/sync/pull_delta":
                    try:
                        since = int(parse_qs(parsed.query).get("since_seq", ["0"])[0])
                        with parent._lock, sync_connection(parent.conn) as conn:
                            result = pull_delta(conn, since, bootstrap=not self.secure)
                        self._send_json(result)
                    except (ValueError, KeyError, sqlite3.Error) as exc:
                        self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                    return

                if path == "/api/v2/sync/ping":
                    with parent._lock, sync_connection(parent.conn) as conn:
                        db_uuid = database_uuid(conn)
                    self._send_json({"ok": True, "protocol": 3, "app": "Morphism SRS", "version": "0.4.0", "db_uuid": db_uuid,
                                     "profile_id": parent.profile_id, "profile_name": parent.profile_name})
                    return

                if path == "/api/checkout":
                    with parent._lock:
                        if parent.review_controller.remaining_count() == 0:
                            parent.review_controller.start_auto_study()
                        cards_bundle = []
                        saved_idx = parent.review_controller._current_index
                        for i in range(saved_idx, len(parent.review_controller._queue)):
                            parent.review_controller._current_index = i
                            ctx = parent.review_controller.current_prompt_context()
                            if ctx:
                                cards_bundle.append(
                                    {
                                        "card_id": ctx.card.id,
                                        "note_title": ctx.note.title,
                                        "review_mode": ctx.review_mode.value,
                                        "premise_html": ctx.note.premise_html,
                                        "front_html": ctx.card.front_html,
                                        "back_html": ctx.card.back_html,
                                        "siblings": [
                                            {
                                                "step_order": s.step_order,
                                                "title": s.title,
                                                "front_html": s.front_html,
                                                "back_html": s.back_html,
                                                "position": s.position,
                                            }
                                            for s in ctx.conditioning_siblings
                                        ],
                                    }
                                )
                        parent.review_controller._current_index = saved_idx
                        self._send_json({"cards": cards_bundle})
                    return

                if path == "/api/v2/sync/pull":
                    with parent._lock:
                        payload = {
                            "version": "2.2.0",
                            "exported_at": datetime.now(timezone.utc).isoformat(),
                            "folders": _fetch_table_dicts(parent.conn, "SELECT * FROM course_folders"),
                            "courses": _fetch_table_dicts(parent.conn, "SELECT * FROM courses"),
                            "notes": _fetch_table_dicts(parent.conn, "SELECT * FROM notes"),
                            "course_notes": _fetch_table_dicts(parent.conn, "SELECT * FROM course_notes"),
                            "cards": _fetch_table_dicts(parent.conn, "SELECT * FROM cards"),
                            "card_schedules": _fetch_table_dicts(parent.conn, "SELECT * FROM card_schedules"),
                            "edges": _fetch_table_dicts(parent.conn, "SELECT * FROM edges"),
                            "tags": _fetch_table_dicts(parent.conn, "SELECT * FROM tags"),
                            "note_tags": _fetch_table_dicts(parent.conn, "SELECT * FROM note_tags"),
                            "review_logs": _fetch_table_dicts(parent.conn, "SELECT * FROM review_logs ORDER BY id DESC LIMIT 5000"),
                            "scratch_pages": _fetch_table_dicts(parent.conn, "SELECT * FROM scratchbook_pages"),
                        }
                    self._send_json(payload)
                    return

                if path.startswith("/media/"):
                    filename = path.replace("/media/", "").strip()
                    file_path = (parent.media_vault.media_dir / filename).resolve()
                    if file_path.parent != parent.media_vault.media_dir.resolve():
                        self.send_error(HTTPStatus.NOT_FOUND)
                        return
                    if file_path.exists() and file_path.is_file():
                        data = file_path.read_bytes()
                        content_type = parent.media_vault.get_mime_type(file_path)
                        self._send_bytes(data, content_type)
                        return

                self.send_error(HTTPStatus.NOT_FOUND)

            def do_POST(self) -> None:
                if not self._check_token():
                    self.send_error(HTTPStatus.FORBIDDEN, "Invalid or missing sync token")
                    return

                parsed = urlparse(self.path)
                path = parsed.path.rstrip("/")
                path = path.replace("/api/v3/", "/api/v2/", 1)
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length < 0 or length > 64 * 1024 * 1024:
                        self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                        return
                except ValueError:
                    self.send_error(HTTPStatus.BAD_REQUEST, "Invalid Content-Length")
                    return
                self.connection.settimeout(60)
                raw = self.rfile.read(length) if length > 0 else b"{}"

                try:
                    if self.secure:
                        raw = open_sealed(parent.session_key, raw, self.aad + b" body " + self.request_proof)
                    payload = json.loads(raw.decode("utf-8"))
                except Exception:
                    self.send_error(HTTPStatus.BAD_REQUEST, "Invalid JSON payload")
                    return

                if path == "/api/v2/sync/push_delta":
                    try:
                        if not isinstance(payload, dict):
                            raise ValueError("Expected an object")
                        with parent._lock, sync_connection(parent.conn) as conn:
                            result = push_delta(conn, payload)
                        parent.event_bus.review_state_changed.emit()
                        parent.event_bus.courses_updated.emit()
                        self._send_json(result)
                    except (ValueError, KeyError, TypeError, sqlite3.Error) as exc:
                        self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                    return

                if path == "/api/checkin":
                    logs = payload.get("logs", [])
                    synced = 0
                    with parent._lock:
                        for item in logs:
                            cid = int(item.get("card_id", 0))
                            r_val = int(item.get("rating", 3))
                            card = parent.review_controller.card_repo.get_by_id(cid)
                            if card and card.id:
                                parent.review_controller._queue = [card]
                                parent.review_controller._current_index = 0
                                parent.review_controller.submit_rating(RatingEnum(r_val))
                                synced += 1
                    parent.event_bus.courses_updated.emit()
                    self._send_json({"ok": True, "synced": synced})
                    return

                if path == "/api/v2/sync/push":
                    scheds_synced = 0
                    logs_synced = 0

                    with parent._lock, UnitOfWork(parent.conn):
                        # 1. Update Card Schedules from Mobile
                        for s in payload.get("card_schedules", []):
                            cid = s.get("card_id")
                            if cid is not None:
                                parent.conn.execute(
                                    """
                                    UPDATE card_schedules
                                    SET state = ?, step = ?, stability = ?, difficulty = ?,
                                        due_at = ?, last_review_at = ?, reps = ?, lapses = ?,
                                        scheduled_days = ?, elapsed_days = ?, is_suspended = ?, is_buried = ?
                                    WHERE card_id = ?;
                                    """,
                                    (
                                        s.get("state", 0),
                                        s.get("step", 0),
                                        s.get("stability"),
                                        s.get("difficulty"),
                                        s.get("due_at"),
                                        s.get("last_review_at"),
                                        s.get("reps", 0),
                                        s.get("lapses", 0),
                                        s.get("scheduled_days", 0),
                                        s.get("elapsed_days", 0),
                                        1 if s.get("is_suspended") else 0,
                                        1 if s.get("is_buried") else 0,
                                        cid,
                                    ),
                                )
                                scheds_synced += 1

                        # 2. Insert Review Logs from Mobile
                        for log in payload.get("review_logs", []):
                            cid = log.get("card_id")
                            rev_at = log.get("reviewed_at")
                            if cid and rev_at:
                                log_uuid = log.get("uuid") or secrets.token_hex(16)
                                parent.conn.execute(
                                    """
                                    INSERT OR IGNORE INTO review_logs (
                                        uuid, card_id, rating, reviewed_at, duration_ms,
                                        prev_state, prev_step, prev_stability, prev_difficulty, prev_due_at, prev_last_review_at,
                                        new_state, new_step, new_stability, new_difficulty, new_due_at,
                                        elapsed_days, scheduled_days
                                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                                    """,
                                    (
                                        log_uuid,
                                        cid,
                                        log.get("rating", 3),
                                        rev_at,
                                        log.get("duration_ms", 0),
                                        log.get("prev_state", log.get("state_before", 0)),
                                        log.get("prev_step", 0),
                                        log.get("prev_stability", log.get("stability_before")),
                                        log.get("prev_difficulty", log.get("difficulty_before")),
                                        log.get("prev_due_at"),
                                        log.get("prev_last_review_at"),
                                        log.get("new_state", log.get("state_after", 2)),
                                        log.get("new_step", 0),
                                        log.get("new_stability", log.get("stability_after")),
                                        log.get("new_difficulty", log.get("difficulty_after")),
                                        log.get("new_due_at", rev_at),
                                        log.get("elapsed_days", 0.0),
                                        log.get("scheduled_days", 0.0),
                                    ),
                                )
                                logs_synced += 1

                    parent.event_bus.review_state_changed.emit()
                    parent.event_bus.courses_updated.emit()
                    self._send_json({
                        "ok": True,
                        "schedules_synced": scheds_synced,
                        "logs_synced": logs_synced,
                        "synced_at": datetime.now(timezone.utc).isoformat(),
                    })
                    return

                self.send_error(HTTPStatus.NOT_FOUND)

        class SyncHTTPServer(ThreadingHTTPServer):
            allow_reuse_address = False

        DEFAULT_PORT = 8765
        try:
            self._httpd = SyncHTTPServer(("0.0.0.0", DEFAULT_PORT), Handler)
        except OSError:
            self._httpd = SyncHTTPServer(("0.0.0.0", 0), Handler)
        self.port = int(self._httpd.server_address[1])
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self.url

    @property
    def url(self) -> str:
        ip = get_lan_ip()
        fragment = urlencode({"key": encode(self.session_key), "uuid": self.db_uuid})
        return f"morphism-sync://{ip}:{self.port}/#{fragment}"

    @property
    def connect_info(self) -> dict:
        ip = get_lan_ip()
        return {
            "protocol": 3, "pairing_url": self.url, "db_uuid": self.db_uuid,
            "profile_id": self.profile_id, "profile_name": self.profile_name,
            "server": f"http://{ip}:{self.port}",
        }

    def stop(self) -> None:
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            finally:
                self._httpd = None
                self._thread = None
