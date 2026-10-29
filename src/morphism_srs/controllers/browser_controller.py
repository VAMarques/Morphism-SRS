from __future__ import annotations

import sqlite3

from morphism_srs.controllers.event_bus import EventBus
from morphism_srs.storage.repositories.browser_repo import BrowserNoteRowItem, BrowserRepository, BrowserRowItem
from morphism_srs.storage.repositories.card_repo import CardRepository
from morphism_srs.storage.repositories.note_repo import NoteRepository
from morphism_srs.storage.unit_of_work import UnitOfWork


class BrowserController:
    """Controller for the 3-panel Mass Card Browser."""

    def __init__(self, conn: sqlite3.Connection, event_bus: EventBus) -> None:
        self.conn = conn
        self.event_bus = event_bus
        self.browser_repo = BrowserRepository(conn)
        self.card_repo = CardRepository(conn)
        self.note_repo = NoteRepository(conn)

    def search(
        self,
        query_text: str = "",
        course_id: int | None = None,
        folder_id: int | None = None,
        tag_filter: str | None = None,
        state_filter: int | None = None,
        review_mode_filter: str | None = None,
        suspended_filter: bool | None = None,
    ) -> list[BrowserRowItem]:
        return self.browser_repo.search_cards(
            query_text=query_text,
            course_id=course_id,
            folder_id=folder_id,
            tag_filter=tag_filter,
            state_filter=state_filter,
            review_mode_filter=review_mode_filter,
            suspended_filter=suspended_filter,
        )

    search_cards = search

    def search_notes(
        self,
        query_text: str = "",
        course_id: int | None = None,
        tag_filter: str | None = None,
        review_mode_filter: str | None = None,
    ) -> list[BrowserNoteRowItem]:
        return self.browser_repo.search_notes(
            query_text=query_text,
            course_id=course_id,
            tag_filter=tag_filter,
            review_mode_filter=review_mode_filter,
        )

    def suspend_cards(self, card_ids: list[int], suspended: bool) -> None:
        with UnitOfWork(self.conn):
            self.card_repo.set_suspended_bulk(card_ids, suspended)
        self.event_bus.courses_updated.emit()

    def reset_cards(self, card_ids: list[int]) -> None:
        with UnitOfWork(self.conn):
            self.card_repo.reset_schedules_bulk(card_ids)
        self.event_bus.courses_updated.emit()

    def add_tag_to_notes(self, note_ids: list[int], tag: str) -> None:
        with UnitOfWork(self.conn):
            self.note_repo.add_tag_bulk(note_ids, tag)
        self.event_bus.courses_updated.emit()

    def remove_tag_from_notes(self, note_ids: list[int], tag: str) -> None:
        with UnitOfWork(self.conn):
            self.note_repo.remove_tag_bulk(note_ids, tag)
        self.event_bus.courses_updated.emit()

    def move_notes_to_course(self, note_ids: list[int], target_course_id: int) -> None:
        if not note_ids:
            return
        placeholders = ",".join("?" for _ in note_ids)
        with UnitOfWork(self.conn):
            self.conn.execute(
                f"UPDATE notes SET course_id = ? WHERE id IN ({placeholders});",
                [target_course_id, *note_ids],
            )
            self.conn.execute(
                f"DELETE FROM edges WHERE source_note_id IN ({placeholders}) OR target_note_id IN ({placeholders});",
                [*note_ids, *note_ids],
            )
        self.event_bus.courses_updated.emit()
