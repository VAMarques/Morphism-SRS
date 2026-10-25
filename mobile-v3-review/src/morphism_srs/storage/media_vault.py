from __future__ import annotations

import hashlib
import mimetypes
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

MIME_BY_EXT: dict[str, str] = {
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".webp": "image/webp",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
}


class MediaVault:
    """Content-addressable (SHA-256) media vault for SVG, PNG, WebP, JPG, and GIF assets."""

    def __init__(self, conn: sqlite3.Connection, media_dir: Path) -> None:
        self.conn = conn
        self.media_dir = media_dir
        self.media_dir.mkdir(parents=True, exist_ok=True)

    def store_bytes(self, data: bytes, original_name: str) -> tuple[str, str]:
        """Stores bytes deduplicated by SHA-256. Returns (sha256_hash, stored_filename)."""
        ext = Path(original_name).suffix.lower() or ".png"
        if ext not in MIME_BY_EXT:
            guessed, _ = mimetypes.guess_type(original_name)
            mime_type = guessed or "application/octet-stream"
        else:
            mime_type = MIME_BY_EXT[ext]

        sha256_hash = hashlib.sha256(data).hexdigest()
        stored_filename = f"{sha256_hash}{ext}"
        target_path = self.media_dir / stored_filename
        if not target_path.exists():
            target_path.write_bytes(data)

        now_iso = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """
            INSERT OR IGNORE INTO media_assets (sha256_hash, original_name, mime_type, byte_size, created_at)
            VALUES (?, ?, ?, ?, ?);
            """,
            (sha256_hash, original_name, mime_type, len(data), now_iso),
        )
        return sha256_hash, stored_filename

    def store_file(self, source_path: Path) -> tuple[str, str]:
        data = source_path.read_bytes()
        return self.store_bytes(data, source_path.name)

    def resolve_path(self, filename_or_hash: str) -> Path | None:
        direct = self.media_dir / filename_or_hash
        if direct.exists() and direct.is_file():
            return direct
        matches = list(self.media_dir.glob(f"{filename_or_hash}.*"))
        if matches:
            return matches[0]
        return None

    def get_mime_type(self, path: Path) -> str:
        ext = path.suffix.lower()
        if ext in MIME_BY_EXT:
            return MIME_BY_EXT[ext]
        guessed, _ = mimetypes.guess_type(path.name)
        return guessed or "application/octet-stream"
