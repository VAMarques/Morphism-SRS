#!/usr/bin/env python3
r"""
Standalone Prototype 1 -> Prototype 2 Migration Utility (`tools/migrate_proto1.py`).

CRITICAL ARCHITECTURAL ISOLATION:
This utility is 100% standalone and decoupled from `src/morphism_srs/`.
It uses only Python's standard library (`sqlite3`, `json`, `uuid`, `re`, `pathlib`, `argparse`)
so that Prototype 2's core runtime has ZERO legacy coupling to Prototype 1.

Responsibilities:
1. Scans Prototype 1's directory (`Courses/**/*.json`, `scheduling/*_scheduling.json`,
   `scheduling/*_reviews.json`, `scratchbook/*.txt`).
2. Maps Prototype 1's legacy `note_type` / `type="ProofSequenceCard"` into Prototype 2's
   unified `notes.review_mode IN ('standard', 'serial', 'cloze')` and `cards` with `step_order`.
3. Sanitizes stray mathematical `<` and `>` into native LaTeX `\lt ` and `\gt ` while
   preserving valid HTML tags (`<br>`, `<ul>`, `<img>`, etc.).
4. Migrates all FSRS v5 scheduling states (`card_schedules`) and historical `review_logs`.
5. Migrates all `scratchbook/*.txt` pages into `scratchbook_pages`.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import uuid


ALLOWED_HTML_TAGS = {
    "br", "hr", "b", "strong", "i", "em", "u", "s", "sub", "sup",
    "ul", "ol", "li", "p", "div", "span", "code", "pre", "blockquote",
    "table", "thead", "tbody", "tr", "th", "td", "img", "svg", "path",
    "g", "rect", "circle", "ellipse", "line", "polyline", "polygon", "text",
}
TAG_CANDIDATE_RE = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9_:-]*)(\s[^<>]*|/?)>")


def sanitize_math_html_standalone(raw: str) -> str:
    if not raw:
        return ""
    preserved: list[str] = []

    def _keep(m: re.Match[str]) -> str:
        if m.group(2).lower() in ALLOWED_HTML_TAGS:
            idx = len(preserved)
            preserved.append(m.group(0))
            return f"\x00TAG_{idx}\x00"
        return m.group(0)

    s1 = TAG_CANDIDATE_RE.sub(_keep, raw)
    s2 = s1.replace("<", r"\lt ").replace(">", r"\gt ")
    return re.sub(r"\x00TAG_(\d+)\x00", lambda m: preserved[int(m.group(1))], s2)


def det_uuid(namespace_str: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"morphism.proto1.{namespace_str}"))


def normalize_tag(tag: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", tag.strip().lower()).strip("_")


def ensure_folder_chain(conn: sqlite3.Connection, folder_path: str, now_iso: str) -> int | None:
    parts = [p.strip() for p in folder_path.replace("\\", "/").split("/") if p.strip()]
    parent_id: int | None = None
    for part in parts:
        if parent_id is None:
            row = conn.execute(
                "SELECT id FROM course_folders WHERE parent_id IS NULL AND name = ?;",
                (part,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT id FROM course_folders WHERE parent_id = ? AND name = ?;",
                (parent_id, part),
            ).fetchone()
        if row:
            parent_id = int(row[0])
        else:
            f_uuid = det_uuid(f"folder:{parent_id}:{part}")
            cur = conn.execute(
                """
                INSERT INTO course_folders (uuid, name, parent_id, display_order, is_expanded, created_at, updated_at)
                VALUES (?, ?, ?, 0, 1, ?, ?);
                """,
                (f_uuid, part, parent_id, now_iso, now_iso),
            )
            parent_id = int(cur.lastrowid)
    return parent_id


def ensure_tag(conn: sqlite3.Connection, tag_name: str) -> int | None:
    clean = normalize_tag(tag_name)
    if not clean:
        return None
    row = conn.execute("SELECT id FROM tags WHERE name = ?;", (clean,)).fetchone()
    if row:
        return int(row[0])
    cur = conn.execute("INSERT INTO tags (name, color_hex) VALUES (?, '#cba6f7');", (clean,))
    return int(cur.lastrowid)


def parse_fsrs_schedule(
    card_db_id: int,
    sched_dict: dict | None,
    now_iso: str,
) -> tuple:
    if not sched_dict:
        return (card_db_id, 0, 0, None, None, now_iso, None, 0, 0, 0, 0, 0, 0)

    last_rev = sched_dict.get("last_review")
    raw_state = int(sched_dict.get("state", 0))
    if last_rev is None and sched_dict.get("stability") is None:
        v2_state = 0
    else:
        v2_state = raw_state if raw_state in (0, 1, 2, 3) else 2

    step = sched_dict.get("step", 0)
    stability = float(sched_dict["stability"]) if sched_dict.get("stability") is not None else None
    difficulty = float(sched_dict["difficulty"]) if sched_dict.get("difficulty") is not None else None
    due_at = str(sched_dict.get("due") or now_iso)
    reps = int(sched_dict.get("reps", 1 if last_rev else 0))
    lapses = int(sched_dict.get("lapses", 0))
    scheduled_days = int(sched_dict.get("scheduled_days", 0))
    elapsed_days = int(sched_dict.get("elapsed_days", 0))

    return (
        card_db_id,
        v2_state,
        step,
        stability,
        difficulty,
        due_at,
        str(last_rev) if last_rev else None,
        reps,
        lapses,
        scheduled_days,
        elapsed_days,
        0,
        0,
    )


def migrate_proto1_to_v2(
    proto1_root: Path,
    target_db_path: Path,
    schema_sql_path: Path,
) -> dict[str, int]:
    now_iso = datetime.now(timezone.utc).isoformat()
    target_db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(target_db_path))
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")

    if schema_sql_path.exists():
        conn.executescript(schema_sql_path.read_text(encoding="utf-8"))
        conn.execute("PRAGMA foreign_keys = ON;")

    stats = {
        "courses": 0,
        "notes": 0,
        "cards": 0,
        "edges": 0,
        "reviews": 0,
        "scratch_pages": 0,
    }

    courses_dir = proto1_root / "Courses"
    scheduling_dir = proto1_root / "scheduling"
    scratch_dir = proto1_root / "scratchbook"

    if courses_dir.exists():
        course_files = sorted(courses_dir.rglob("*.json"))
    else:
        course_files = []

    with conn:
        for c_idx, c_file in enumerate(course_files):
            try:
                c_data = json.loads(c_file.read_text(encoding="utf-8"))
            except Exception:
                continue

            course_name = str(c_data.get("name") or c_file.stem).strip()
            rel_parent = c_file.parent.relative_to(courses_dir)
            rel_folder_str = "" if str(rel_parent) == "." else str(rel_parent).replace("\\", "/")
            json_folder_str = str(c_data.get("folder_path") or "").strip()
            effective_folder = json_folder_str or rel_folder_str

            folder_id = ensure_folder_chain(conn, effective_folder, now_iso) if effective_folder else None
            c_uuid = det_uuid(f"course:{course_name}")

            existing_course = conn.execute(
                "SELECT id FROM courses WHERE uuid = ? OR name = ?;",
                (c_uuid, course_name),
            ).fetchone()
            if existing_course:
                course_db_id = int(existing_course[0])
            else:
                cur = conn.execute(
                    """
                    INSERT INTO courses (
                        uuid, name, folder_id, description, color_hex,
                        desired_retention, display_order, is_archived, created_at, updated_at
                    ) VALUES (?, ?, ?, '', '#89b4fa', 0.90, ?, 0, ?, ?);
                    """,
                    (c_uuid, course_name, folder_id, c_idx, now_iso, now_iso),
                )
                course_db_id = int(cur.lastrowid)
                stats["courses"] += 1

            ext_sched_map: dict[str, dict] = {}
            sched_file = scheduling_dir / f"{course_name}_scheduling.json"
            if sched_file.exists():
                try:
                    ext_sched_map = json.loads(sched_file.read_text(encoding="utf-8"))
                except Exception:
                    ext_sched_map = {}

            p1_note_to_db_id: dict[str, int] = {}
            p1_card_to_db_id: dict[str, int] = {}

            for n_data in c_data.get("notes", []):
                p1_note_id = str(n_data.get("note_id") or uuid.uuid4())
                n_uuid = det_uuid(f"note:{course_name}:{p1_note_id}")
                title = str(n_data.get("title") or "Untitled").strip()
                pos_x = float(n_data.get("x") or 0.0)
                pos_y = float(n_data.get("y") or 0.0)
                retention = n_data.get("desired_retention")
                retention_val = float(retention) if retention is not None else None

                raw_note_type = str(n_data.get("note_type") or "standard").lower()
                raw_cards = n_data.get("cards", [])
                has_proof_seq = any(str(rc.get("type")) == "ProofSequenceCard" for rc in raw_cards)

                if raw_note_type in ("serial", "serial_sequence", "serial_sequence_single") or has_proof_seq:
                    review_mode = "serial"
                elif raw_note_type == "cloze":
                    review_mode = "cloze"
                else:
                    review_mode = "standard"

                premise_parts: list[str] = []
                for rc in raw_cards:
                    if rc.get("premise"):
                        premise_parts.append( sanitize_math_html_standalone(str(rc["premise"])) )
                premise_html = "<br>".join(dict.fromkeys(p for p in premise_parts if p))

                existing_note = conn.execute("SELECT id FROM notes WHERE uuid = ?;", (n_uuid,)).fetchone()
                if existing_note:
                    note_db_id = int(existing_note[0])
                else:
                    cur = conn.execute(
                        """
                        INSERT INTO notes (
                            uuid, course_id, external_key, title, premise_html,
                            pos_x, pos_y, review_mode, desired_retention, is_pinned,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?);
                        """,
                        (
                            n_uuid,
                            course_db_id,
                            p1_note_id[:36],
                            title,
                            premise_html,
                            pos_x,
                            pos_y,
                            review_mode,
                            retention_val,
                            now_iso,
                            now_iso,
                        ),
                    )
                    note_db_id = int(cur.lastrowid)
                    stats["notes"] += 1

                p1_note_to_db_id[p1_note_id] = note_db_id

                for raw_tag in n_data.get("tags", []):
                    tid = ensure_tag(conn, str(raw_tag))
                    if tid is not None:
                        conn.execute(
                            "INSERT OR IGNORE INTO note_tags (note_id, tag_id) VALUES (?, ?);",
                            (note_db_id, tid),
                        )

                step_counter = 0
                for rc in raw_cards:
                    p1_item_id = str(rc.get("item_id") or uuid.uuid4())
                    rc_type = str(rc.get("type") or "Flashcard")
                    sched_dict = ext_sched_map.get(p1_item_id) or rc.get("fsrs_card")

                    if rc_type == "ProofSequenceCard" and isinstance(rc.get("steps"), list) and rc["steps"]:
                        for s_idx, step_text in enumerate(rc["steps"]):
                            c_uuid = det_uuid(f"card:{p1_item_id}:step:{s_idx}")
                            existing_c = conn.execute("SELECT id FROM cards WHERE uuid = ?;", (c_uuid,)).fetchone()
                            if existing_c:
                                card_db_id = int(existing_c[0])
                            else:
                                front_str = f"Prove Step {s_idx + 1}"
                                back_str = sanitize_math_html_standalone(str(step_text))
                                cur = conn.execute(
                                    """
                                    INSERT INTO cards (
                                        uuid, note_id, step_order, title,
                                        front_html, back_html, hint_html, created_at, updated_at
                                    ) VALUES (?, ?, ?, ?, ?, ?, '', ?, ?);
                                    """,
                                    (
                                        c_uuid,
                                        note_db_id,
                                        step_counter,
                                        str(rc.get("title") or f"Step {s_idx + 1}"),
                                        front_str,
                                        back_str,
                                        now_iso,
                                        now_iso,
                                    ),
                                )
                                card_db_id = int(cur.lastrowid)
                                stats["cards"] += 1

                            sched_tuple = parse_fsrs_schedule(card_db_id, sched_dict, now_iso)
                            conn.execute(
                                """
                                INSERT OR REPLACE INTO card_schedules (
                                    card_id, state, step, stability, difficulty, due_at, last_review_at,
                                    reps, lapses, scheduled_days, elapsed_days, is_suspended, is_buried
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                                """,
                                sched_tuple,
                            )
                            if s_idx == 0:
                                p1_card_to_db_id[p1_item_id] = card_db_id
                            step_counter += 1
                    else:
                        c_uuid = det_uuid(f"card:{p1_item_id}")
                        existing_c = conn.execute("SELECT id FROM cards WHERE uuid = ?;", (c_uuid,)).fetchone()
                        if existing_c:
                            card_db_id = int(existing_c[0])
                        else:
                            front_str = sanitize_math_html_standalone(str(rc.get("front") or title))
                            back_str = sanitize_math_html_standalone(str(rc.get("back") or ""))
                            cur = conn.execute(
                                """
                                INSERT INTO cards (
                                    uuid, note_id, step_order, title,
                                    front_html, back_html, hint_html, created_at, updated_at
                                ) VALUES (?, ?, ?, ?, ?, ?, '', ?, ?);
                                """,
                                (
                                    c_uuid,
                                    note_db_id,
                                    step_counter,
                                    str(rc.get("title") or ""),
                                    front_str,
                                    back_str,
                                    now_iso,
                                    now_iso,
                                ),
                            )
                            card_db_id = int(cur.lastrowid)
                            stats["cards"] += 1

                        sched_tuple = parse_fsrs_schedule(card_db_id, sched_dict, now_iso)
                        conn.execute(
                            """
                            INSERT OR REPLACE INTO card_schedules (
                                card_id, state, step, stability, difficulty, due_at, last_review_at,
                                reps, lapses, scheduled_days, elapsed_days, is_suspended, is_buried
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                            """,
                            sched_tuple,
                        )
                        p1_card_to_db_id[p1_item_id] = card_db_id
                        step_counter += 1

            for ed in c_data.get("edges", []):
                src_p1 = str(ed.get("source_id") or "")
                dst_p1 = str(ed.get("target_id") or "")
                src_db = p1_note_to_db_id.get(src_p1)
                dst_db = p1_note_to_db_id.get(dst_p1)
                if src_db and dst_db and src_db != dst_db:
                    e_uuid = det_uuid(f"edge:{course_name}:{src_p1}:{dst_p1}")
                    cur = conn.execute(
                        """
                        INSERT OR IGNORE INTO edges (
                            uuid, course_id, source_note_id, target_note_id, label, weight, created_at
                        ) VALUES (?, ?, ?, ?, ?, 1.0, ?);
                        """,
                        (e_uuid, course_db_id, src_db, dst_db, str(ed.get("label") or ""), now_iso),
                    )
                    if cur.rowcount > 0:
                        stats["edges"] += 1

            rev_file = scheduling_dir / f"{course_name}_reviews.json"
            if rev_file.exists():
                try:
                    rev_list = json.loads(rev_file.read_text(encoding="utf-8"))
                except Exception:
                    rev_list = []

                for r_idx, rv in enumerate(rev_list):
                    p1_cid = str(rv.get("card_id") or "")
                    card_db_id = p1_card_to_db_id.get(p1_cid)
                    if not card_db_id:
                        continue
                    rev_time = str(rv.get("review_time") or now_iso)
                    rating = max(1, min(4, int(rv.get("rating") or 3)))
                    r_uuid = det_uuid(f"rev:{course_name}:{p1_cid}:{rev_time}:{r_idx}")
                    new_st = int(rv.get("state") or 2)
                    if new_st not in (0, 1, 2, 3):
                        new_st = 2
                    stab = float(rv["stability"]) if rv.get("stability") is not None else None
                    diff = float(rv["difficulty"]) if rv.get("difficulty") is not None else None
                    el_days = float(rv.get("elapsed_days") or 0.0)
                    sc_days = float(rv.get("scheduled_days") or 0.0)

                    cur = conn.execute(
                        """
                        INSERT OR IGNORE INTO review_logs (
                            uuid, card_id, rating, reviewed_at, duration_ms,
                            prev_state, prev_step, prev_stability, prev_difficulty, prev_due_at, prev_last_review_at,
                            new_state, new_step, new_stability, new_difficulty, new_due_at,
                            elapsed_days, scheduled_days
                        ) VALUES (?, ?, ?, ?, 0, 0, 0, NULL, NULL, ?, NULL, ?, 0, ?, ?, ?, ?, ?);
                        """,
                        (
                            r_uuid,
                            card_db_id,
                            rating,
                            rev_time,
                            rev_time,
                            new_st,
                            stab,
                            diff,
                            rev_time,
                            el_days,
                            sc_days,
                        ),
                    )
                    if cur.rowcount > 0:
                        stats["reviews"] += 1

        if scratch_dir.exists():
            for s_idx, txt_file in enumerate(sorted(scratch_dir.glob("*.txt"))):
                s_uuid = det_uuid(f"scratch:{txt_file.stem}")
                content = txt_file.read_text(encoding="utf-8", errors="replace")
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO scratchbook_pages (
                        uuid, title, content_text, display_order, updated_at
                    ) VALUES (?, ?, ?, ?, ?);
                    """,
                    (s_uuid, txt_file.stem, content, s_idx, now_iso),
                )
                if cur.rowcount > 0:
                    stats["scratch_pages"] += 1

    conn.close()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Standalone Prototype 1 -> Prototype 2 SQLite Migrator")
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(r"c:\repos\New SRS Project"),
        help="Path to Prototype 1 root directory",
    )
    parser.add_argument(
        "--target-db",
        type=Path,
        required=True,
        help="Path to target Prototype 2 SQLite database (morphism_v2.sqlite3)",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "src" / "morphism_srs" / "storage" / "schema_v2.sql",
        help="Path to schema_v2.sql",
    )
    args = parser.parse_args()
    summary = migrate_proto1_to_v2(args.source, args.target_db, args.schema)
    print("Migration completed:", json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
