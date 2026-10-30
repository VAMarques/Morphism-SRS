from __future__ import annotations

import sqlite3

from morphism_srs.controllers.commands import CommandStack, UndoableCommand
from morphism_srs.controllers.event_bus import EventBus
from morphism_srs.domain.models import EdgeModel, NoteMetrics, NoteModel
from morphism_srs.domain.scheduler_engine import SchedulerEngine
from morphism_srs.services.layout_service import LayoutService
from morphism_srs.storage.repositories.card_repo import CardRepository
from morphism_srs.storage.repositories.course_repo import CourseRepository
from morphism_srs.storage.repositories.note_repo import NoteRepository
from morphism_srs.storage.unit_of_work import UnitOfWork


class ExplorerController:
    """Controller for the Graph Explorer (DAG operations, bulk mutations, layout, and Ctrl+Z undo)."""

    def __init__(self, conn: sqlite3.Connection, event_bus: EventBus) -> None:
        self.conn = conn
        self.event_bus = event_bus
        self.course_repo = CourseRepository(conn)
        self.note_repo = NoteRepository(conn)
        self.card_repo = CardRepository(conn)
        self.undo_stack = CommandStack()

    def get_course_graph(self, course_id: int) -> tuple[list[NoteModel], list[EdgeModel], dict[int, NoteMetrics]]:
        notes = self.note_repo.list_by_course(course_id, include_children=True)
        edges = self.note_repo.list_edges_by_course(course_id)
        metrics: dict[int, NoteMetrics] = {}
        for n in notes:
            if n.id is not None:
                scheds = [c.schedule for c in n.cards if c.schedule is not None]
                metrics[n.id] = SchedulerEngine.compute_note_metrics(n.id, scheds)
        return notes, edges, metrics

    def record_nodes_moved(
        self,
        course_id: int,
        old_positions: dict[int, tuple[float, float]],
        new_positions: dict[int, tuple[float, float]],
    ) -> None:
        if not new_positions or old_positions == new_positions:
            return
        with UnitOfWork(self.conn):
            self.note_repo.update_positions_bulk(new_positions, course_id=course_id)

        def _undo() -> None:
            with UnitOfWork(self.conn):
                self.note_repo.update_positions_bulk(old_positions, course_id=course_id)
            self.event_bus.notes_updated.emit(course_id)

        self.undo_stack.push(
            UndoableCommand(
                description=f"Undid moving {len(new_positions)} node(s)",
                undo_fn=_undo,
            )
        )

    def auto_layout_course(self, course_id: int, note_ids_subset: list[int] | None = None) -> None:
        notes = self.note_repo.list_by_course(course_id, include_children=False)
        edges = self.note_repo.list_edges_by_course(course_id)
        target_ids = note_ids_subset or [n.id for n in notes if n.id is not None and not n.is_pinned]
        if not target_ids:
            return
        old_pos = {n.id: (n.pos_x, n.pos_y) for n in notes if n.id in target_ids}
        computed = LayoutService.compute_layered_layout(
            note_ids=target_ids,
            edges=[(e.source_note_id, e.target_note_id) for e in edges],
        )
        if note_ids_subset is not None and old_pos and computed:
            xs = [x for x, y in old_pos.values()]
            ys = [y for x, y in old_pos.values()]
            orig_cx = sum(xs) / len(xs)
            orig_cy = sum(ys) / len(ys)

            c_xs = [x for x, y in computed.values()]
            c_ys = [y for x, y in computed.values()]
            comp_cx = sum(c_xs) / len(c_xs)
            comp_cy = sum(c_ys) / len(c_ys)

            dx = orig_cx - comp_cx
            dy = orig_cy - comp_cy

            computed = {
                nid: (round((x + dx) / 20.0) * 20.0, round((y + dy) / 20.0) * 20.0)
                for nid, (x, y) in computed.items()
            }
        self.record_nodes_moved(course_id, old_pos, computed)
        self.event_bus.notes_updated.emit(course_id)

    def create_edge(self, course_id: int, source_id: int, target_id: int) -> EdgeModel | None:
        with UnitOfWork(self.conn):
            edge = self.note_repo.create_edge(
                EdgeModel(course_id=course_id, source_note_id=source_id, target_note_id=target_id)
            )
        if edge and edge.id is not None:
            eid = edge.id

            def _undo() -> None:
                with UnitOfWork(self.conn):
                    self.note_repo.delete_edge_by_id(eid)
                self.event_bus.notes_updated.emit(course_id)

            self.undo_stack.push(UndoableCommand(description="Undid edge creation", undo_fn=_undo))
            self.event_bus.notes_updated.emit(course_id)
        return edge

    def delete_edge(self, course_id: int, source_id: int, target_id: int) -> None:
        with UnitOfWork(self.conn):
            self.note_repo.delete_edge(source_id, target_id)

        def _undo() -> None:
            with UnitOfWork(self.conn):
                self.note_repo.create_edge(
                    EdgeModel(course_id=course_id, source_note_id=source_id, target_note_id=target_id)
                )
            self.event_bus.notes_updated.emit(course_id)

        self.undo_stack.push(UndoableCommand(description="Undid edge deletion", undo_fn=_undo))
        self.event_bus.notes_updated.emit(course_id)

    def bulk_add_tag(self, course_id: int, note_ids: list[int], tag_name: str) -> None:
        with UnitOfWork(self.conn):
            self.note_repo.add_tag_bulk(note_ids, tag_name)
        self.event_bus.notes_updated.emit(course_id)

    def bulk_suspend_notes(self, course_id: int, note_ids: list[int], suspended: bool) -> None:
        card_ids: list[int] = []
        for nid in note_ids:
            for c in self.card_repo.list_by_note(nid):
                if c.id is not None:
                    card_ids.append(c.id)
        with UnitOfWork(self.conn):
            self.card_repo.set_suspended_bulk(card_ids, suspended)
        self.event_bus.notes_updated.emit(course_id)

    def bulk_delete_notes(self, course_id: int, note_ids: list[int], bridge_edges: bool = False) -> None:
        with UnitOfWork(self.conn):
            for nid in note_ids:
                self.note_repo.delete(nid, bridge_edges=bridge_edges)
        self.event_bus.notes_updated.emit(course_id)

    def undo_last_action(self) -> str | None:
        msg = self.undo_stack.undo()
        if msg:
            self.event_bus.status_message.emit(msg, 3500)
        return msg
