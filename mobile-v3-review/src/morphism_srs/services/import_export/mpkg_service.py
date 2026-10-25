from __future__ import annotations

import json
import re
import sqlite3
import zipfile
from pathlib import Path

from morphism_srs.services.import_export.json_service import JsonImportExportService
from morphism_srs.storage.media_vault import MediaVault


class MpkgService:
    """Packs and unpacks .mpkg (ZIP) deck archives containing course.json, manifest.json, and media assets."""

    MEDIA_REF_RE = re.compile(r"morphism://media/([a-zA-Z0-9_.-]+)")

    def __init__(self, conn: sqlite3.Connection, media_vault: MediaVault) -> None:
        self.conn = conn
        self.media_vault = media_vault
        self.json_service = JsonImportExportService(conn)

    def export_mpkg(
        self,
        course_id: int,
        target_path: Path,
        include_scheduling: bool = False,
    ) -> None:
        course_dict = self.json_service.export_course_dict(course_id, include_scheduling=include_scheduling)
        course_json_str = json.dumps(course_dict, indent=2, ensure_ascii=False)

        referenced_files = set(self.MEDIA_REF_RE.findall(course_json_str))
        manifest = {
            "package_version": "2.0",
            "course_uuid": course_dict["course"]["uuid"],
            "course_name": course_dict["course"]["name"],
            "include_scheduling": include_scheduling,
            "media_files": sorted(referenced_files),
        }

        target_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(target_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
            zf.writestr("course.json", course_json_str)
            for fname in sorted(referenced_files):
                resolved = self.media_vault.resolve_path(fname)
                if resolved and resolved.is_file():
                    zf.write(resolved, arcname=f"media/{resolved.name}")

    def import_mpkg(self, mpkg_path: Path, include_scheduling: bool = True) -> int:
        with zipfile.ZipFile(mpkg_path, "r") as zf:
            names = set(zf.namelist())
            if "course.json" not in names:
                raise ValueError("Invalid .mpkg archive: missing course.json")

            for member in names:
                if member.startswith("media/") and not member.endswith("/"):
                    raw_bytes = zf.read(member)
                    fname = Path(member).name
                    self.media_vault.store_bytes(raw_bytes, fname)

            course_data = json.loads(zf.read("course.json").decode("utf-8"))
            return self.json_service.import_course_dict(course_data, include_scheduling=include_scheduling)
