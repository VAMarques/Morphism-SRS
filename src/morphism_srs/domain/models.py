from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from morphism_srs.domain.enums import CardState, NoteReviewMode
from morphism_srs.domain.ids import generate_uuid


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class CourseFolderModel:
    id: int | None = None
    uuid: str = field(default_factory=generate_uuid)
    name: str = ""
    parent_id: int | None = None
    display_order: int = 0
    is_expanded: bool = True
    fsrs_weights_json: str | None = None
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)


@dataclass
class CourseModel:
    id: int | None = None
    uuid: str = field(default_factory=generate_uuid)
    name: str = ""
    folder_id: int | None = None
    description: str = ""
    color_hex: str = "#89b4fa"
    desired_retention: float = 0.80
    display_order: int = 0
    is_archived: bool = False
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)


@dataclass
class TagModel:
    id: int | None = None
    name: str = ""
    color_hex: str = "#cba6f7"


@dataclass
class CardScheduleModel:
    card_id: int
    state: CardState = CardState.NEW
    step: int | None = 0
    stability: float | None = None
    difficulty: float | None = None
    due_at: str = field(default_factory=_now_iso)
    last_review_at: str | None = None
    reps: int = 0
    lapses: int = 0
    scheduled_days: int = 0
    elapsed_days: int = 0
    is_suspended: bool = False
    is_buried: bool = False


@dataclass
class CardModel:
    id: int | None = None
    uuid: str = field(default_factory=generate_uuid)
    note_id: int = 0
    step_order: int = 0
    title: str = ""
    front_html: str = ""
    back_html: str = ""
    hint_html: str = ""
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    schedule: CardScheduleModel | None = None


@dataclass
class NoteModel:
    id: int | None = None
    uuid: str = field(default_factory=generate_uuid)
    course_id: int | None = None
    external_key: str | None = None
    title: str = ""
    premise_html: str = ""
    pos_x: float = 0.0
    pos_y: float = 0.0
    review_mode: NoteReviewMode = NoteReviewMode.STANDARD
    desired_retention: float | None = None
    is_pinned: bool = False
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    tags: list[str] = field(default_factory=list)
    cards: list[CardModel] = field(default_factory=list)


@dataclass
class EdgeModel:
    id: int | None = None
    uuid: str = field(default_factory=generate_uuid)
    course_id: int = 0
    source_note_id: int = 0
    target_note_id: int = 0
    label: str = ""
    weight: float = 1.0
    created_at: str = field(default_factory=_now_iso)


@dataclass
class ReviewLogModel:
    id: int | None = None
    uuid: str = field(default_factory=generate_uuid)
    card_id: int = 0
    rating: int = 3
    reviewed_at: str = field(default_factory=_now_iso)
    duration_ms: int = 0
    prev_state: int = 0
    prev_step: int | None = 0
    prev_stability: float | None = None
    prev_difficulty: float | None = None
    prev_due_at: str | None = None
    prev_last_review_at: str | None = None
    new_state: int = 0
    new_step: int | None = 0
    new_stability: float | None = None
    new_difficulty: float | None = None
    new_due_at: str = field(default_factory=_now_iso)
    elapsed_days: float = 0.0
    scheduled_days: float = 0.0


@dataclass
class ScratchbookPageModel:
    id: int | None = None
    uuid: str = field(default_factory=generate_uuid)
    title: str = "Scratchpad"
    content_text: str = ""
    display_order: int = 0
    updated_at: str = field(default_factory=_now_iso)


@dataclass
class NoteMetrics:
    note_id: int
    card_count: int
    r_min: float
    r_avg: float
    p_joint: float
    due_count: int
    new_count: int


@dataclass
class SiblingCardContext:
    card_id: int
    step_order: int
    title: str
    front_html: str
    back_html: str
    position: str  # "before" | "after"


@dataclass
class ReviewPromptContext:
    """Prepared context for rendering a card in standard, serial, or cloze mode."""

    card: CardModel
    note: NoteModel
    course_name: str
    review_mode: NoteReviewMode
    conditioning_siblings: list[SiblingCardContext] = field(default_factory=list)
    intervals_preview: dict[int, str] = field(default_factory=dict)
