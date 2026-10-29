from __future__ import annotations

import json
import math
from dataclasses import replace
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Iterable

from fsrs import Card as FSRSCard
from fsrs import Rating as FSRSRating
from fsrs import Scheduler as FSRSScheduler
from fsrs import State as FSRSState

from morphism_srs.domain.enums import CardState, NoteReviewMode, RatingEnum
from morphism_srs.domain.models import (
    CardModel,
    CardScheduleModel,
    NoteMetrics,
    NoteModel,
    ReviewLogModel,
    ReviewPromptContext,
    SiblingCardContext,
)


def parse_utc(iso_str: str | None) -> datetime:
    if not iso_str:
        return datetime.now(timezone.utc)
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return datetime.now(timezone.utc)


def format_interval_delta(delta: timedelta) -> str:
    total_seconds = max(0.0, delta.total_seconds())
    minutes = total_seconds / 60.0
    hours = total_seconds / 3600.0
    days = total_seconds / 86400.0
    if minutes < 1.0:
        return "<1m"
    if minutes < 60.0:
        return f"{int(round(minutes))}m"
    if hours < 24.0:
        return f"{int(round(hours))}h"
    if days < 30.0:
        return f"{int(round(days))}d"
    if days < 365.0:
        return f"{days / 30.0:.1f}mo"
    return f"{days / 365.0:.1f}y"


class SchedulerEngine:
    """Pure FSRS v5 scheduling engine, retrievability metrics, and DAG topological sorting."""

    FSRS_DECAY: float = -0.5
    FSRS_FACTOR: float = 19.0 / 81.0

    def __init__(
        self,
        desired_retention: float = 0.80,
        weights_json: str | list[float] | None = None,
        enable_fuzzing: bool = False,
        learning_steps: tuple[timedelta, ...] | None = None,
        relearning_steps: tuple[timedelta, ...] | None = None,
    ) -> None:
        self.desired_retention = max(0.70, min(0.99, float(desired_retention)))
        params = None
        if isinstance(weights_json, str) and weights_json.strip():
            try:
                loaded = json.loads(weights_json)
                if isinstance(loaded, list) and len(loaded) in (17, 19):
                    params = tuple(float(x) for x in loaded)
            except Exception:
                params = None
        elif isinstance(weights_json, (list, tuple)) and len(weights_json) in (17, 19):
            params = tuple(float(x) for x in weights_json)

        if params is not None and len(params) == 17:
            # Legacy FSRS-4.5 vectors have no short-term coefficients.
            params = params + (0.51655, 0.6621)

        steps_learn = learning_steps if learning_steps is not None else (timedelta(minutes=10),)
        steps_relearn = relearning_steps if relearning_steps is not None else (timedelta(minutes=10),)

        kwargs: dict = {
            "desired_retention": self.desired_retention,
            "learning_steps": steps_learn,
            "relearning_steps": steps_relearn,
            "maximum_interval": 36500,
            "enable_fuzzing": enable_fuzzing,
        }
        if params is not None:
            kwargs["parameters"] = params
        self.scheduler = FSRSScheduler(**kwargs)

    @staticmethod
    def schedule_to_fsrs_card(sched: CardScheduleModel) -> FSRSCard:
        fc = FSRSCard(card_id=sched.card_id)
        if sched.state == CardState.NEW or sched.last_review_at is None:
            fc.state = FSRSState.Learning
            fc.step = 0
            fc.stability = None
            fc.difficulty = None
            fc.due = parse_utc(sched.due_at)
            fc.last_review = None
        else:
            state_val = int(sched.state)
            if state_val == int(CardState.REVIEW):
                fc.state = FSRSState.Review
            elif state_val == int(CardState.RELEARNING):
                fc.state = FSRSState.Relearning
            else:
                fc.state = FSRSState.Learning
            fc.step = sched.step
            fc.stability = sched.stability
            fc.difficulty = sched.difficulty
            fc.due = parse_utc(sched.due_at)
            fc.last_review = parse_utc(sched.last_review_at)
        return fc

    @classmethod
    def compute_card_retrievability(
        cls,
        sched: CardScheduleModel | None,
        now: datetime | None = None,
    ) -> float:
        """Computes R(t, S) = (1 + FACTOR * t / S)^DECAY in [0.0, 1.0]."""
        if sched is None or sched.state == CardState.NEW or sched.last_review_at is None:
            return 0.0
        if sched.stability is None or sched.stability <= 0.0:
            return 0.0
        now_dt = now or datetime.now(timezone.utc)
        last_dt = parse_utc(sched.last_review_at)
        elapsed_days = max(0.0, (now_dt - last_dt).total_seconds() / 86400.0)
        r = (1.0 + cls.FSRS_FACTOR * (elapsed_days / sched.stability)) ** cls.FSRS_DECAY
        return max(0.0, min(1.0, float(r)))

    @classmethod
    def compute_note_metrics(
        cls,
        note_id: int,
        schedules: Iterable[CardScheduleModel],
        now: datetime | None = None,
    ) -> NoteMetrics:
        now_dt = now or datetime.now(timezone.utc)
        sched_list = [s for s in schedules if not s.is_suspended]
        if not sched_list:
            return NoteMetrics(
                note_id=note_id,
                card_count=0,
                r_min=0.0,
                r_avg=0.0,
                p_joint=0.0,
                due_count=0,
                new_count=0,
            )

        r_values: list[float] = []
        due_count = 0
        new_count = 0
        learning_count = 0
        for s in sched_list:
            if s.state == CardState.NEW or s.last_review_at is None:
                new_count += 1
                r_values.append(0.0)
            else:
                r = cls.compute_card_retrievability(s, now_dt)
                r_values.append(r)
                if s.state == CardState.LEARNING:
                    learning_count += 1
                if parse_utc(s.due_at) <= now_dt or s.state in (CardState.LEARNING, CardState.RELEARNING):
                    due_count += 1

        r_min = min(r_values) if r_values else 0.0
        r_avg = sum(r_values) / len(r_values) if r_values else 0.0
        p_joint = math.prod(r_values) if r_values else 0.0
        return NoteMetrics(
            note_id=note_id,
            card_count=len(sched_list),
            r_min=r_min,
            r_avg=r_avg,
            p_joint=p_joint,
            due_count=due_count,
            new_count=new_count,
            learning_count=learning_count,
        )

    def preview_intervals(
        self,
        sched: CardScheduleModel,
        now: datetime | None = None,
    ) -> dict[int, str]:
        """Simulates all 4 FSRS ratings without mutating state and returns human-readable intervals."""
        now_dt = now or datetime.now(timezone.utc)
        base_card = self.schedule_to_fsrs_card(sched)
        result: dict[int, str] = {}
        for r_enum in (RatingEnum.AGAIN, RatingEnum.HARD, RatingEnum.GOOD, RatingEnum.EASY):
            sim_card, _ = self.scheduler.review_card(
                base_card,
                FSRSRating(int(r_enum)),
                review_datetime=now_dt,
            )
            delta = sim_card.due - now_dt
            result[int(r_enum)] = format_interval_delta(delta)
        return result

    def rate_card(
        self,
        sched: CardScheduleModel,
        rating: RatingEnum | int,
        now: datetime | None = None,
        duration_ms: int = 0,
    ) -> tuple[CardScheduleModel, ReviewLogModel]:
        """Applies an FSRS rating and returns (updated_schedule, review_log_entry)."""
        now_dt = now or datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()
        rating_val = int(rating)

        prev_state = int(sched.state)
        prev_step = sched.step
        prev_stability = sched.stability
        prev_difficulty = sched.difficulty
        prev_due_at = sched.due_at
        prev_last_review_at = sched.last_review_at

        fsrs_card = self.schedule_to_fsrs_card(sched)
        updated_fc, _ = self.scheduler.review_card(
            fsrs_card,
            FSRSRating(rating_val),
            review_datetime=now_dt,
        )

        new_state_val = int(updated_fc.state)
        new_due_iso = updated_fc.due.isoformat()
        elapsed_days = (
            max(0.0, (now_dt - parse_utc(prev_last_review_at)).total_seconds() / 86400.0)
            if prev_last_review_at
            else 0.0
        )
        scheduled_days = max(0.0, (updated_fc.due - now_dt).total_seconds() / 86400.0)

        new_reps = sched.reps + 1
        new_lapses = sched.lapses + (1 if rating_val == int(RatingEnum.AGAIN) and prev_state == int(CardState.REVIEW) else 0)

        new_sched = CardScheduleModel(
            card_id=sched.card_id,
            state=CardState(new_state_val),
            step=updated_fc.step,
            stability=float(updated_fc.stability) if updated_fc.stability is not None else None,
            difficulty=float(updated_fc.difficulty) if updated_fc.difficulty is not None else None,
            due_at=new_due_iso,
            last_review_at=now_iso,
            reps=new_reps,
            lapses=new_lapses,
            scheduled_days=int(round(scheduled_days)),
            elapsed_days=int(round(elapsed_days)),
            is_suspended=sched.is_suspended,
            is_buried=sched.is_buried,
        )

        log_entry = ReviewLogModel(
            card_id=sched.card_id,
            rating=rating_val,
            reviewed_at=now_iso,
            duration_ms=duration_ms,
            prev_state=prev_state,
            prev_step=prev_step,
            prev_stability=prev_stability,
            prev_difficulty=prev_difficulty,
            prev_due_at=prev_due_at,
            prev_last_review_at=prev_last_review_at,
            new_state=new_state_val,
            new_step=updated_fc.step,
            new_stability=new_sched.stability,
            new_difficulty=new_sched.difficulty,
            new_due_at=new_due_iso,
            elapsed_days=elapsed_days,
            scheduled_days=scheduled_days,
        )
        return new_sched, log_entry

    def reschedule_from_logs(
        self,
        card_id: int,
        logs: list[ReviewLogModel],
        base_schedule: CardScheduleModel | None = None,
        initial_schedule: CardScheduleModel | None = None,
    ) -> CardScheduleModel:
        """Replays review history chronologically to recompute schedule under current FSRS weights."""
        sched = replace(initial_schedule) if initial_schedule is not None else CardScheduleModel(
            card_id=card_id,
            is_suspended=base_schedule.is_suspended if base_schedule else False,
            is_buried=base_schedule.is_buried if base_schedule else False,
        )
        sorted_logs = sorted(logs, key=lambda lg: (parse_utc(lg.reviewed_at), lg.uuid))
        for lg in sorted_logs:
            rev_dt = parse_utc(lg.reviewed_at)
            sched, _ = self.rate_card(sched, RatingEnum(lg.rating), now=rev_dt, duration_ms=lg.duration_ms)
        return sched

    def build_prompt_context(
        self,
        target_card: CardModel,
        note: NoteModel,
        course_name: str,
        now: datetime | None = None,
    ) -> ReviewPromptContext:
        """Builds the conditioning context for standard, serial P(A_i | A_j, j<i), or cloze P(A_i | A_j, j!=i)."""
        mode = note.review_mode
        siblings: list[SiblingCardContext] = []
        sorted_cards = sorted(note.cards, key=lambda c: (c.step_order, c.id or 0))

        if mode == NoteReviewMode.SERIAL:
            for c in sorted_cards:
                if c.id == target_card.id:
                    break
                if c.step_order < target_card.step_order or (c.step_order == target_card.step_order and (c.id or 0) < (target_card.id or 0)):
                    siblings.append(
                        SiblingCardContext(
                            card_id=c.id or 0,
                            step_order=c.step_order,
                            title=c.title,
                            front_html=c.front_html,
                            back_html=c.back_html,
                            position="before",
                        )
                    )
        elif mode == NoteReviewMode.CLOZE:
            seen_target = False
            for c in sorted_cards:
                if c.id == target_card.id:
                    seen_target = True
                    continue
                siblings.append(
                    SiblingCardContext(
                        card_id=c.id or 0,
                        step_order=c.step_order,
                        title=c.title,
                        front_html=c.front_html,
                        back_html=c.back_html,
                        position="after" if seen_target else "before",
                    )
                )

        sched = target_card.schedule or CardScheduleModel(card_id=target_card.id or 0)
        intervals = self.preview_intervals(sched, now=now)
        return ReviewPromptContext(
            card=target_card,
            note=note,
            course_name=course_name,
            review_mode=mode,
            conditioning_siblings=siblings,
            intervals_preview=intervals,
        )

    @staticmethod
    def topological_sort_notes(
        note_ids: list[int],
        edges: list[tuple[int, int]],
    ) -> list[int]:
        """Kahn's algorithm topological sort on note_ids with cycle fallback."""
        node_set = set(note_ids)
        in_degree: dict[int, int] = {nid: 0 for nid in note_ids}
        adj: dict[int, list[int]] = {nid: [] for nid in note_ids}

        for src, dst in edges:
            if src in node_set and dst in node_set and src != dst:
                adj[src].append(dst)
                in_degree[dst] += 1

        queue: deque[int] = deque(nid for nid in note_ids if in_degree[nid] == 0)
        ordered: list[int] = []

        while queue:
            u = queue.popleft()
            ordered.append(u)
            for v in adj[u]:
                in_degree[v] -= 1
                if in_degree[v] == 0:
                    queue.append(v)

        if len(ordered) < len(note_ids):
            seen = set(ordered)
            for nid in note_ids:
                if nid not in seen:
                    ordered.append(nid)
        return ordered
