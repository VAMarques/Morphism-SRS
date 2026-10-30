from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import sqlite3
import time

from morphism_srs.controllers.commands import CommandStack, UndoableCommand
from morphism_srs.controllers.event_bus import EventBus
from morphism_srs.domain.enums import CardState, NoteReviewMode, RatingEnum
from morphism_srs.domain.models import CardModel, CardScheduleModel, ReviewPromptContext
from morphism_srs.domain.scheduler_engine import SchedulerEngine
from morphism_srs.storage.repositories.card_repo import CardRepository
from morphism_srs.storage.repositories.course_repo import CourseRepository
from morphism_srs.storage.repositories.folder_repo import FolderRepository
from morphism_srs.storage.repositories.note_repo import NoteRepository
from morphism_srs.storage.repositories.gamification_repo import GamificationRepository
from morphism_srs.storage.repositories.review_repo import ReviewRepository
from morphism_srs.storage.unit_of_work import UnitOfWork


@dataclass
class CustomStudyConfig:
    course_ids: list[int] = field(default_factory=list)
    note_ids: list[int] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    include_prerequisite_ancestors: bool = False
    only_due_or_new: bool = False
    ahead_days: int = 0
    failed_within_days: int | None = None
    sort_criterion: str = "topological_due"
    # "topological_due" | "bottleneck_r_min" | "joint_retrieval" | "lowest_stability" | "most_lapses"
    max_cards: int = 100
    cram_sandbox: bool = False


class ReviewController:
    """Manages active study sessions (Auto-Study & Custom Study), FSRS ratings, and Ctrl+Z undo."""

    def __init__(self, conn: sqlite3.Connection, event_bus: EventBus) -> None:
        self.conn = conn
        self.event_bus = event_bus
        self.folder_repo = FolderRepository(conn)
        self.course_repo = CourseRepository(conn)
        self.note_repo = NoteRepository(conn)
        self.card_repo = CardRepository(conn)
        self.review_repo = ReviewRepository(conn)
        self.gamification_repo = GamificationRepository(conn)
        self.undo_stack = CommandStack()

        self._queue: list[CardModel] = []
        self._current_index: int = 0
        self._cram_sandbox: bool = False
        self._card_shown_timestamp: float = time.monotonic()
        self._session_card_mastered: dict[int, bool] = {}

    @property
    def is_cram_sandbox(self) -> bool:
        return self._cram_sandbox

    def remaining_count(self) -> int:
        return max(0, len(self._queue) - self._current_index)

    def total_count(self) -> int:
        return len(self._queue)

    def current_Index_1based(self) -> int:
        return min(len(self._queue), self._current_index + 1)

    def remaining_note_cards(self, note: NoteModel) -> int:
        if not note or not note.cards:
            return 1
        unmastered = sum(
            1 for c in note.cards
            if c.id is not None and not self._session_card_mastered.get(c.id, False)
        )
        return max(1, unmastered)

    def start_auto_study(
        self,
        course_ids: list[int] | None = None,
        folder_id: int | None = None,
    ) -> int:
        target_courses = list(course_ids or [])
        if folder_id is not None:
            desc_folders = set(self.folder_repo.get_descendant_folder_ids(folder_id))
            all_courses = self.course_repo.list_all()
            for c in all_courses:
                if c.id is not None and c.folder_id in desc_folders:
                    target_courses.append(c.id)

        cfg = CustomStudyConfig(
            course_ids=target_courses,
            only_due_or_new=True,
            sort_criterion="topological_due",
            max_cards=500,
            cram_sandbox=False,
        )
        return self.start_custom_study(cfg)

    def start_custom_study(self, cfg: CustomStudyConfig) -> int:
        self.undo_stack.clear()
        self._cram_sandbox = cfg.cram_sandbox
        self._session_card_mastered.clear()

        target_note_ids = list(cfg.note_ids)
        if cfg.include_prerequisite_ancestors and target_note_ids:
            target_note_ids = self.note_repo.get_ancestors_recursive(target_note_ids)

        candidates = self.review_repo.fetch_study_candidates(
            course_ids=cfg.course_ids or None,
            note_ids=target_note_ids or None,
            tags=cfg.tags or None,
            only_due_or_new=cfg.only_due_or_new,
            ahead_days=cfg.ahead_days,
            failed_within_days=cfg.failed_within_days,
        )

        if not candidates:
            self._queue = []
            self._current_index = 0
            return 0

        self._queue = self._order_candidates(candidates, cfg.sort_criterion)[: max(1, cfg.max_cards)]
        self._current_index = 0
        self._card_shown_timestamp = time.monotonic()
        self.event_bus.review_session_started.emit()
        return len(self._queue)

    def start_note_study(self, note_id: int, force_all_cards: bool = False) -> int:
        """
        Starts a focused study session for a single Note clicked in the Graph Explorer.
        If force_all_cards is False, prioritizes Due/New cards first and falls back to all cards
        if none are currently due. If force_all_cards is True, queues all cards in step_order.
        """
        self.undo_stack.clear()
        self._cram_sandbox = False
        self._session_card_mastered.clear()

        if not force_all_cards:
            due_or_new = self.review_repo.fetch_study_candidates(
                note_ids=[note_id],
                only_due_or_new=True,
            )
            if due_or_new:
                self._queue = sorted(due_or_new, key=lambda c: c.step_order)
                self._current_index = 0
                self._card_shown_timestamp = time.monotonic()
                self.event_bus.review_session_started.emit()
                return len(self._queue)

        all_cards = self.review_repo.fetch_study_candidates(
            note_ids=[note_id],
            only_due_or_new=False,
        )
        self._queue = sorted(all_cards, key=lambda c: c.step_order)
        self._current_index = 0
        self._card_shown_timestamp = time.monotonic()
        if self._queue:
            self.event_bus.review_session_started.emit()
        return len(self._queue)

    def _order_candidates(self, cards: list[CardModel], criterion: str) -> list[CardModel]:
        now_dt = datetime.now(timezone.utc)
        note_ids = sorted({c.note_id for c in cards})
        note_schedules: dict[int, list[CardScheduleModel]] = {}
        for nid in note_ids:
            note_cards = self.card_repo.list_by_note(nid)
            note_schedules[nid] = [nc.schedule for nc in note_cards if nc.schedule is not None]

        note_metrics = {
            nid: SchedulerEngine.compute_note_metrics(nid, scheds, now_dt)
            for nid, scheds in note_schedules.items()
        }

        if criterion == "bottleneck_r_min":
            return sorted(
                cards,
                key=lambda c: (
                    note_metrics[c.note_id].r_min if c.note_id in note_metrics else 0.0,
                    c.step_order,
                ),
            )
        if criterion == "joint_retrieval":
            return sorted(
                cards,
                key=lambda c: (
                    note_metrics[c.note_id].p_joint if c.note_id in note_metrics else 0.0,
                    c.step_order,
                ),
            )
        if criterion == "lowest_stability":
            return sorted(
                cards,
                key=lambda c: (
                    c.schedule.stability if (c.schedule and c.schedule.stability is not None) else -1.0,
                    c.step_order,
                ),
            )
        if criterion == "most_lapses":
            return sorted(
                cards,
                key=lambda c: (
                    -(c.schedule.lapses if c.schedule else 0),
                    c.step_order,
                ),
            )

        # Default: topological_due (Kahn's topological sort across DAG edges + step_order)
        course_ids = sorted({n.course_id for nid in note_ids if (n := self.note_repo.get_by_id(nid, include_children=False))})
        all_edges: list[tuple[int, int]] = []
        for cid in course_ids:
            for e in self.note_repo.list_edges_by_course(cid):
                all_edges.append((e.source_note_id, e.target_note_id))

        topo_notes = SchedulerEngine.topological_sort_notes(note_ids, all_edges)
        topo_rank = {nid: idx for idx, nid in enumerate(topo_notes)}
        return sorted(
            cards,
            key=lambda c: (
                topo_rank.get(c.note_id, 999999),
                c.step_order,
                c.schedule.due_at if c.schedule else "",
            ),
        )

    def _get_unresolved_learning_cards(self) -> list[CardModel]:
        """Finds unique cards from the active session that still require review:
        cards in Learning/Relearning or cards not yet mastered with Good/Easy."""
        seen_ids: set[int] = set()
        unresolved: list[CardModel] = []
        for c in self._queue:
            if c.id is not None and c.id not in seen_ids:
                seen_ids.add(c.id)
                is_mastered = self._session_card_mastered.get(c.id, False)
                if not is_mastered:
                    fresh = self.card_repo.get_by_id(c.id)
                    unresolved.append(fresh or c)
                elif not self._cram_sandbox:
                    fresh = self.card_repo.get_by_id(c.id)
                    if fresh is not None and fresh.schedule is not None:
                        if fresh.schedule.state in (CardState.LEARNING, CardState.RELEARNING):
                            unresolved.append(fresh)
        return unresolved

    def current_prompt_context(self) -> ReviewPromptContext | None:
        if self._current_index < 0:
            return None

        if self._current_index >= len(self._queue):
            unresolved = self._get_unresolved_learning_cards()
            if unresolved:
                # Cycle back starting at the earliest step (step_order ascending, e.g. Step 1 if needed)
                self._queue.extend(sorted(unresolved, key=lambda c: (c.note_id, c.step_order)))
            else:
                return None

        if self._current_index >= len(self._queue):
            return None

        card = self._queue[self._current_index]
        if card.id is not None:
            fresh_card = self.card_repo.get_by_id(card.id)
            if fresh_card is not None:
                card = fresh_card
                self._queue[self._current_index] = card

        note = self.note_repo.get_by_id(card.note_id, include_children=True)
        if note is None:
            return None
        course = self.course_repo.get_by_id(note.course_id) if note.course_id else None
        course_name = course.name if course else "Course"
        retention = (
            note.desired_retention
            if note.desired_retention is not None
            else (course.desired_retention if course else 0.80)
        )
        weights = self.folder_repo.resolve_effective_fsrs_weights(course.folder_id if course else None)
        engine = SchedulerEngine(desired_retention=retention, weights_json=weights)
        return engine.build_prompt_context(card, note, course_name)

    def submit_rating(self, rating: RatingEnum | int) -> bool:
        """Applies rating to current card, advances queue, and pushes UndoableCommand. Returns True if more cards remain."""
        if self._current_index < 0 or self._current_index >= len(self._queue):
            return False

        card = self._queue[self._current_index]
        if card.id is None:
            return False

        duration_ms = int(max(0.0, (time.monotonic() - self._card_shown_timestamp) * 1000.0))
        note = self.note_repo.get_by_id(card.note_id, include_children=False)
        course = self.course_repo.get_by_id(note.course_id) if (note and note.course_id) else None
        retention = (
            note.desired_retention
            if (note and note.desired_retention is not None)
            else (course.desired_retention if course else 0.80)
        )
        weights = self.folder_repo.resolve_effective_fsrs_weights(course.folder_id if course else None)
        engine = SchedulerEngine(desired_retention=retention, weights_json=weights)

        rating_val = int(rating)
        is_serial = (note is not None and note.review_mode == NoteReviewMode.SERIAL)
        prev_idx = self._current_index
        prev_queue_len = len(self._queue)
        prev_sched = card.schedule
        prev_mastered = self._session_card_mastered.get(card.id, False)

        # Gamification: decoupled streak and XP tracking triggered on each review rating
        try:
            self.gamification_repo.record_entry()
            self.gamification_repo.add_review_xp(1.0)
        except Exception:
            pass

        # In a serial note:
        # - Again: do NOT advance; stay on the current step so the user dominates it before advancing.
        # - Hard: DOES advance to next step, but remains unmastered so when the stack ends,
        #   it cycles back to the earliest unmastered step.
        # - Good / Easy: advances and marks the step as mastered.

        if self._cram_sandbox:
            if is_serial and rating_val == int(RatingEnum.AGAIN):
                self._card_shown_timestamp = time.monotonic()
                self._session_card_mastered[card.id] = False
                self.undo_stack.push(
                    UndoableCommand(
                        description=f"Undo sandbox rating on '{card.title or (note.title if note else 'card')}'",
                        undo_fn=lambda: (
                            self._restore_queue_index(prev_idx),
                            self._session_card_mastered.update({card.id: prev_mastered}),
                        ),
                    )
                )
                self.event_bus.review_state_changed.emit()
                return True

            self._session_card_mastered[card.id] = (rating_val in (int(RatingEnum.GOOD), int(RatingEnum.EASY)))
            self._current_index += 1
            self._card_shown_timestamp = time.monotonic()
            self.undo_stack.push(
                UndoableCommand(
                    description=f"Undo sandbox rating on '{card.title or (note.title if note else 'card')}'",
                    undo_fn=lambda: (
                        self._restore_queue_index(prev_idx),
                        self._session_card_mastered.update({card.id: prev_mastered}),
                    ),
                )
            )
            self.event_bus.review_state_changed.emit()
            return self._current_index < len(self._queue) or bool(self._get_unresolved_learning_cards())

        sched = card.schedule or CardScheduleModel(card_id=card.id)
        new_sched, log_entry = engine.rate_card(sched, rating_val, duration_ms=duration_ms)

        with UnitOfWork(self.conn) as uow:
            saved_log = self.review_repo.record_review(new_sched, log_entry)
            uow.log_operation("review_logs", saved_log.uuid, "INSERT", {"card_id": card.id, "rating": rating_val})

        log_id = saved_log.id
        card.schedule = new_sched

        # Track mastery for session
        if is_serial:
            # Serial steps require Good or Easy to be considered mastered
            self._session_card_mastered[card.id] = (rating_val in (int(RatingEnum.GOOD), int(RatingEnum.EASY)))
        else:
            # For standard notes, graduated to Review means mastered
            self._session_card_mastered[card.id] = (new_sched.state == CardState.REVIEW)

        # 1. Serial note rated Again: Stay on the current step so the user dominates it before advancing.
        if is_serial and rating_val == int(RatingEnum.AGAIN):
            self._card_shown_timestamp = time.monotonic()

            def _undo_serial_again() -> None:
                if log_id is not None:
                    with UnitOfWork(self.conn):
                        restored = self.review_repo.undo_review(log_id)
                        if restored is not None:
                            card.schedule = restored
                self._session_card_mastered[card.id] = prev_mastered
                self._restore_queue_index(prev_idx)

            self.undo_stack.push(
                UndoableCommand(
                    description=f"Undid Again on '{note.title if note else 'Card'}' (Step {card.step_order + 1})",
                    undo_fn=_undo_serial_again,
                )
            )
            self.event_bus.review_state_changed.emit()
            return True

        # 2. Advance to next card (Hard, Good, Easy, or non-serial Again)
        self._current_index += 1
        self._card_shown_timestamp = time.monotonic()
        card_appended = False

        # For non-serial notes, append to queue immediately so it appears at the end of the current batch.
        # For serial notes, we let the entire stack play out sequentially (1 -> 2 -> ... -> N),
        # and when the stack finishes, current_prompt_context() cycles back to the earliest unmastered step in order.
        if not is_serial and new_sched.state in (CardState.LEARNING, CardState.RELEARNING):
            card_clone = replace(card, schedule=new_sched)
            self._queue.append(card_clone)
            card_appended = True

        def _undo_db_and_queue() -> None:
            if card_appended and len(self._queue) > prev_queue_len:
                self._queue.pop()
            if log_id is not None:
                with UnitOfWork(self.conn):
                    restored = self.review_repo.undo_review(log_id)
                    if restored is not None:
                        card.schedule = restored
            self._session_card_mastered[card.id] = prev_mastered
            self._restore_queue_index(prev_idx)

        self.undo_stack.push(
            UndoableCommand(
                description=f"Undid review of '{note.title if note else 'Card'}'",
                undo_fn=_undo_db_and_queue,
            )
        )
        self.event_bus.review_state_changed.emit()
        return self._current_index < len(self._queue) or bool(self._get_unresolved_learning_cards())

    def _restore_queue_index(self, idx: int) -> None:
        self._current_index = max(0, min(idx, len(self._queue) - 1))
        self._card_shown_timestamp = time.monotonic()
        self.event_bus.review_state_changed.emit()

    def undo_last_review(self) -> str | None:
        msg = self.undo_stack.undo()
        if msg:
            self.event_bus.status_message.emit(msg, 3500)
        return msg
