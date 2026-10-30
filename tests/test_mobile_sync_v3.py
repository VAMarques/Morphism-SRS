"""Wire-level tests against a real LAN HTTP server and a portable SQLite snapshot."""
import unittest
from contextlib import closing
import gzip
import json
import sqlite3
import time
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

import test_delta_sync_and_portable as fixtures
from morphism_srs.controllers.event_bus import EventBus
from morphism_srs.controllers.review_controller import ReviewController
from morphism_srs.services.mobile_server import EphemeralMobileServer
from morphism_srs.services.delta_sync import pull_delta, TABLE_KEYS
from morphism_srs.services.sync_crypto import seal, open_sealed, encode, decode
from morphism_srs.storage.media_vault import MediaVault
from cryptography.exceptions import InvalidTag
from morphism_srs.services.qr_generator import encode_qr_matrix


class TestMobileV3(unittest.TestCase):
    log = fixtures.TestDeltaSync.log
    batch = fixtures.TestDeltaSync.batch
    def setUp(self):
        fixtures.TestDeltaSync.setUp(self)
        self.bus = EventBus()
        self.vault = MediaVault(self.conn, self.root / "media")
        self.server = EphemeralMobileServer(self.conn, ReviewController(self.conn, self.bus), self.vault, self.bus)
        self.server.start()
        self.base = f"http://127.0.0.1:{self.server.port}"

    def tearDown(self):
        self.server.stop()
        fixtures.TestDeltaSync.tearDown(self)

    def request(self, path, body=None, *, key=None):
        key = key or self.server.session_key
        aad = f"{'GET' if body is None else 'POST'} {path}".encode()
        proof = seal(key, b"", aad)
        data = None if body is None else seal(key, json.dumps(body).encode(), aad + b" body " + proof)
        req = Request(self.base + path, data=data, headers={"X-Morphism-Auth": encode(proof)})
        for attempt in range(3):
            try:
                with urlopen(req, timeout=5) as response:
                    self.assertEqual(response.headers["Content-Type"], "application/vnd.morphism.encrypted")
                    result = open_sealed(key, response.read(), aad + b" response " + proof)
                return result, req
            except (ConnectionResetError, ConnectionAbortedError):
                if attempt == 2:
                    raise
                import time
                time.sleep(0.1)

    def test_pairing_and_authenticated_encrypted_response(self):
        fields = parse_qs(urlparse(self.server.url).fragment)
        self.assertEqual(decode(fields["key"][0]), self.server.session_key)
        self.assertEqual(fields["uuid"][0], self.bootstrap["db_uuid"])
        raw, req = self.request("/api/v3/sync/ping")
        self.assertEqual(json.loads(raw)["protocol"], 3)
        # A recorded request must not be accepted a second time.
        with self.assertRaises(HTTPError) as error:
            urlopen(req, timeout=5)
        self.assertEqual(error.exception.code, 403)
        with self.assertRaises(HTTPError):
            self.request("/api/v3/sync/ping", key=b"x" * 32)
        with self.assertRaises(HTTPError):
            urlopen(self.base + "/api/v2/sync/pull?token=" + self.server.token, timeout=5)
        with self.assertRaises(HTTPError):
            self.request("/api/v3/sync/pull")
        with self.assertRaises(HTTPError):
            self.request("/api/v3/sync/push", {"card_schedules": []})

    def test_snapshot_is_portable_private_and_cursor_matches(self):
        self.conn.execute("INSERT OR REPLACE INTO app_meta VALUES ('private_secret', '\"never-export\"')")
        raw, _ = self.request("/api/v3/sync/snapshot")
        path = self.root / "download.db"
        path.write_bytes(gzip.decompress(raw))
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertFalse(db.execute("PRAGMA foreign_key_check").fetchall())
            self.assertFalse(db.execute("SELECT 1 FROM sqlite_master WHERE name='cards_fts'").fetchall())
            self.assertFalse(db.execute("SELECT 1 FROM app_meta WHERE key='private_secret'").fetchall())
            for table in TABLE_KEYS:
                self.assertEqual(db.execute(f"SELECT count(*) FROM {table}").fetchone()[0], self.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
            seq = json.loads(db.execute("SELECT value_json FROM app_meta WHERE key='sync_last_pc_seq'").fetchone()[0])
        delta, _ = self.request(f"/api/v3/sync/pull_delta?since_seq={seq}")
        delta = json.loads(delta)
        self.assertEqual(delta["mode"], "delta")
        self.assertFalse(any(delta["upserts"].values()))
        self.assertEqual(delta["media_manifest"], [])

    def test_encrypted_push_retry_wrong_collection_and_body_tampering(self):
        log = self.log()
        body = self.batch(log)
        for _ in range(2):
            result, _ = self.request("/api/v3/sync/push_delta", body)
            self.assertIn(log["uuid"], json.loads(result)["log_ids"])
        self.assertEqual(self.conn.execute("SELECT count(*) FROM review_logs").fetchone()[0], 1)
        with self.assertRaises(HTTPError) as error:
            self.request("/api/v3/sync/push_delta", {**body, "db_uuid": "wrong"})
        self.assertEqual(error.exception.code, 400)
        aad = b"POST /api/v3/sync/push_delta"
        proof = seal(self.server.session_key, b"", aad)
        bad = bytearray(seal(self.server.session_key, b"{}", aad + b" body " + proof)); bad[-1] ^= 1
        req = Request(self.base + "/api/v3/sync/push_delta", data=bytes(bad), headers={"X-Morphism-Auth": encode(proof)})
        with self.assertRaises(HTTPError):
            urlopen(req, timeout=5)

    def test_empty_cursor_stays_delta_and_large_changes_require_snapshot(self):
        self.assertEqual(pull_delta(self.conn, 0, bootstrap=False)["mode"], "delta")
        seq = self.bootstrap["current_seq"]
        self.conn.executemany("UPDATE notes SET title=? WHERE id=?", ((str(i), self.note.id) for i in range(2001)))
        result = pull_delta(self.conn, seq, bootstrap=False)
        self.assertTrue(result["snapshot_required"])
        self.assertNotIn("upserts", result)

    def test_expired_session_and_aad_binding(self):
        key = self.server.session_key
        sealed = seal(key, b"data", b"GET /one")
        with self.assertRaises(InvalidTag):
            open_sealed(key, sealed, b"GET /two")
        self.server._expires = time.monotonic() - 1
        with self.assertRaises(HTTPError):
            self.request("/api/v3/sync/ping")

    def test_qr_keeps_complete_key_and_identity(self):
        # Worst-case IPv4/port still fits the built-in version 6 encoder.
        url = "morphism-sync://255.255.255.255:65535/#key=" + encode(self.server.session_key) + "&uuid=" + self.server.db_uuid
        self.assertLessEqual(len(url.encode()), 134)
        matrix = encode_qr_matrix(url)
        self.assertEqual(len(matrix), 41)
        with self.assertRaises(ValueError):
            encode_qr_matrix("a" * 135)
        try:
            import cv2
            import numpy as np
        except ImportError:
            return  # Independent decoder is optional; no OpenCV app dependency.
        pixels = np.array(matrix, dtype=np.uint8)
        image = np.pad(255 * (1 - pixels), 4, constant_values=255).repeat(8, 0).repeat(8, 1)
        detector = cv2.QRCodeDetectorAruco() if hasattr(cv2, "QRCodeDetectorAruco") else cv2.QRCodeDetector()
        decoded = detector.detectAndDecode(image)[0]
        if not decoded:
            image8 = np.pad(255 * (1 - pixels), 8, constant_values=255).repeat(8, 0).repeat(8, 1)
            decoded = detector.detectAndDecode(image8)[0]
        self.assertEqual(decoded, url)
