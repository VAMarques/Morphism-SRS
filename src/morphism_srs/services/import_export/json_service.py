from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from morphism_srs.domain.enums import CardState, NoteReviewMode
from morphism_srs.domain.ids import generate_uuid
from morphism_srs.domain.models import (
    CardModel,
    CardScheduleModel,
    CourseModel,
    EdgeModel,
    NoteModel,
    ReviewLogModel,
)
from morphism_srs.storage.repositories.card_repo import CardRepository
from morphism_srs.storage.repositories.course_repo import CourseRepository
from morphism_srs.storage.repositories.folder_repo import FolderRepository
from morphism_srs.storage.repositories.note_repo import NoteRepository
from morphism_srs.storage.repositories.review_repo import ReviewRepository
from morphism_srs.storage.unit_of_work import UnitOfWork


class JsonImportExportService:
    """Exports and imports Morphism SRS v2 courses in UUID-preserving JSON format."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.folder_repo = FolderRepository(conn)
        self.course_repo = CourseRepository(conn)
        self.note_repo = NoteRepository(conn)
        self.card_repo = CardRepository(conn)
        self.review_repo = ReviewRepository(conn)

    def export_course_dict(self, course_id: int, include_scheduling: bool = True) -> dict[str, Any]:
        course = self.course_repo.get_by_id(course_id)
        if course is None:
            raise ValueError(f"Course {course_id} not found")

        notes = self.note_repo.list_by_course(course_id, include_children=True)
        edges = self.note_repo.list_edges_by_course(course_id)
        note_id_to_uuid = {n.id: n.uuid for n in notes if n.id is not None}

        notes_payload: list[dict[str, Any]] = []
        for n in notes:
            cards_payload: list[dict[str, Any]] = []
            for c in n.cards:
                c_dict: dict[str, Any] = {
                    "uuid": c.uuid,
                    "step_order": c.step_order,
                    "title": c.title,
                    "front_html": c.front_html,
                    "back_html": c.back_html,
                    "hint_html": c.hint_html,
                }
                if include_scheduling and c.schedule is not None and c.id is not None:
                    s = c.schedule
                    c_dict["schedule"] = {
                        "state": int(s.state),
                        "step": s.step,
                        "stability": s.stability,
                        "difficulty": s.difficulty,
                        "due_at": s.due_at,
                        "last_review_at": s.last_review_at,
                        "reps": s.reps,
                        "lapses": s.lapses,
                        "scheduled_days": s.scheduled_days,
                        "elapsed_days": s.elapsed_days,
                        "is_suspended": s.is_suspended,
                    }
                    logs = self.review_repo.list_logs_for_card(c.id)
                    c_dict["review_logs"] = [
                        {
                            "uuid": lg.uuid,
                            "rating": lg.rating,
                            "reviewed_at": lg.reviewed_at,
                            "duration_ms": lg.duration_ms,
                            "prev_state": lg.prev_state,
                            "prev_step": lg.prev_step,
                            "prev_stability": lg.prev_stability,
                            "prev_difficulty": lg.prev_difficulty,
                            "prev_due_at": lg.prev_due_at,
                            "prev_last_review_at": lg.prev_last_review_at,
                            "new_state": lg.new_state,
                            "new_step": lg.new_step,
                            "new_stability": lg.new_stability,
                            "new_difficulty": lg.new_difficulty,
                            "new_due_at": lg.new_due_at,
                            "elapsed_days": lg.elapsed_days,
                            "scheduled_days": lg.scheduled_days,
                        }
                        for lg in logs
                    ]
                cards_payload.append(c_dict)

            notes_payload.append(
                {
                    "uuid": n.uuid,
                    "external_key": n.external_key,
                    "title": n.title,
                    "premise_html": n.premise_html,
                    "pos_x": n.pos_x,
                    "pos_y": n.pos_y,
                    "review_mode": n.review_mode.value,
                    "desired_retention": n.desired_retention,
                    "is_pinned": n.is_pinned,
                    "tags": n.tags,
                    "cards": cards_payload,
                }
            )

        edges_payload = [
            {
                "uuid": e.uuid,
                "source_note_uuid": note_id_to_uuid.get(e.source_note_id, ""),
                "target_note_uuid": note_id_to_uuid.get(e.target_note_id, ""),
                "label": e.label,
                "weight": e.weight,
            }
            for e in edges
            if e.source_note_id in note_id_to_uuid and e.target_note_id in note_id_to_uuid
        ]

        return {
            "morphism_format": "v2",
            "course": {
                "uuid": course.uuid,
                "name": course.name,
                "description": course.description,
                "color_hex": course.color_hex,
                "desired_retention": course.desired_retention,
                "display_order": course.display_order,
            },
            "notes": notes_payload,
            "edges": edges_payload,
        }

    def export_course_file(self, course_id: int, target_path: Path, include_scheduling: bool = True) -> None:
        data = self.export_course_dict(course_id, include_scheduling=include_scheduling)
        target_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def import_course_dict(self, data: dict[str, Any], include_scheduling: bool = True) -> int:
        course_data = data.get("course", {})
        c_uuid = str(course_data.get("uuid") or generate_uuid())
        c_name = str(course_data.get("name") or "Imported Course")

        with UnitOfWork(self.conn):
            course = self.course_repo.get_by_uuid(c_uuid)
            if course is None:
                existing_by_name = self.course_repo.get_by_name(c_name)
                if existing_by_name is not None:
                    c_name = f"{c_name} (Imported)"
                course = self.course_repo.create(
                    CourseModel(
                        uuid=c_uuid,
                        name=c_name,
                        description=str(course_data.get("description") or ""),
                        color_hex=str(course_data.get("color_hex") or "#89b4fa"),
                        desired_retention=float(course_data.get("desired_retention") or 0.80),
                        display_order=int(course_data.get("display_order") or 0),
                    )
                )
            assert course.id is not None

            uuid_to_note_id: dict[str, int] = {}
            for nd in data.get("notes", []):
                n_uuid = str(nd.get("uuid") or generate_uuid())
                existing_note = self.note_repo.get_by_uuid(n_uuid, include_children=True)
                mode = NoteReviewMode(str(nd.get("review_mode") or "standard"))

                cards_models: list[CardModel] = []
                for idx, cd in enumerate(nd.get("cards", [])):
                    c_uuid = str(cd.get("uuid") or generate_uuid())
                    existing_card = self.card_repo.get_by_uuid(c_uuid)
                    sched_model: CardScheduleModel | None = None
                    if include_scheduling and "schedule" in cd and isinstance(cd["schedule"], dict):
                        sd = cd["schedule"]
                        sched_model = CardScheduleModel(
                            card_id=existing_card.id if existing_card and existing_card.id else 0,
                            state=CardState(int(sd.get("state", 0))),
                            step=sd.get("step", 0),
                            stability=sd.get("stability"),
                            difficulty=sd.get("difficulty"),
                            due_at=str(sd.get("due_at", "")),
                            last_review_at=sd.get("last_review_at"),
                            reps=int(sd.get("reps", 0)),
                            lapses=int(sd.get("lapses", 0)),
                            scheduled_days=int(sd.get("scheduled_days", 0)),
                            elapsed_days=int(sd.get("elapsed_days", 0)),
                            is_suspended=bool(sd.get("is_suspended", False)),
                        )
                    cards_models.append(
                        CardModel(
                            id=existing_card.id if existing_card else None,
                            uuid=c_uuid,
                            step_order=int(cd.get("step_order", idx)),
                            title=str(cd.get("title", "")),
                            front_html=str(cd.get("front_html", "")),
                            back_html=str(cd.get("back_html", "")),
                            hint_html=str(cd.get("hint_html", "")),
                            schedule=sched_model,
                        )
                    )

                if existing_note is None:
                    created_note = self.note_repo.create(
                        NoteModel(
                            uuid=n_uuid,
                            course_id=course.id,
                            external_key=nd.get("external_key"),
                            title=str(nd.get("title", "Untitled")),
                            premise_html=str(nd.get("premise_html", "")),
                            pos_x=float(nd.get("pos_x", 0.0)),
                            pos_y=float(nd.get("pos_y", 0.0)),
                            review_mode=mode,
                            desired_retention=nd.get("desired_retention"),
                            is_pinned=bool(nd.get("is_pinned", False)),
                            tags=[str(t) for t in nd.get("tags", [])],
                            cards=cards_models,
                        )
                    )
                    assert created_note.id is not None
                    uuid_to_note_id[n_uuid] = created_note.id
                else:
                    assert existing_note.id is not None
                    existing_note.title = str(nd.get("title", existing_note.title))
                    existing_note.premise_html = str(nd.get("premise_html", existing_note.premise_html))
                    existing_note.pos_x = float(nd.get("pos_x", existing_note.pos_x))
                    existing_note.pos_y = float(nd.get("pos_y", existing_note.pos_y))
                    existing_note.review_mode = mode
                    existing_note.tags = [str(t) for t in nd.get("tags", [])]
                    existing_note.cards = cards_models
                    self.note_repo.update(existing_note, sync_cards=True)
                    uuid_to_note_id[n_uuid] = existing_note.id

                if include_scheduling:
                    for cd in nd.get("cards", []):
                        c_uuid = str(cd.get("uuid") or "")
                        card_db = self.card_repo.get_by_uuid(c_uuid)
                        if card_db and card_db.id:
                            for lg in cd.get("review_logs", []):
                                lg_uuid = str(lg.get("uuid") or generate_uuid())
                                self.conn.execute(
                                    """
                                    INSERT OR IGNORE INTO review_logs (
                                        uuid, card_id, rating, reviewed_at, duration_ms,
                                        prev_state, prev_step, prev_stability, prev_difficulty, prev_due_at, prev_last_review_at,
                                        new_state, new_step, new_stability, new_difficulty, new_due_at,
                                        elapsed_days, scheduled_days
                                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                                    """,
                                    (
                                        lg_uuid,
                                        card_db.id,
                                        int(lg.get("rating", 3)),
                                        str(lg.get("reviewed_at", "")),
                                        int(lg.get("duration_ms", 0)),
                                        int(lg.get("prev_state", 0)),
                                        lg.get("prev_step"),
                                        lg.get("prev_stability"),
                                        lg.get("prev_difficulty"),
                                        lg.get("prev_due_at"),
                                        lg.get("prev_last_review_at"),
                                        int(lg.get("new_state", 2)),
                                        lg.get("new_step"),
                                        lg.get("new_stability"),
                                        lg.get("new_difficulty"),
                                        str(lg.get("new_due_at", "")),
                                        float(lg.get("elapsed_days", 0.0)),
                                        float(lg.get("scheduled_days", 0.0)),
                                    ),
                                )

            for ed in data.get("edges", []):
                src_uuid = str(ed.get("source_note_uuid") or "")
                dst_uuid = str(ed.get("target_note_uuid") or "")
                src_id = uuid_to_note_id.get(src_uuid)
                dst_id = uuid_to_note_id.get(dst_uuid)
                if src_id and dst_id and src_id != dst_id:
                    self.note_repo.create_edge(
                        EdgeModel(
                            uuid=str(ed.get("uuid") or generate_uuid()),
                            course_id=course.id,
                            source_note_id=src_id,
                            target_note_id=dst_id,
                            label=str(ed.get("label") or ""),
                            weight=float(ed.get("weight") or 1.0),
                        )
                    )

            return course.id

    def import_course_file(self, source_path: Path, include_scheduling: bool = True) -> int:
        data = json.loads(source_path.read_text(encoding="utf-8"))
        return self.import_course_dict(data, include_scheduling=include_scheduling)
