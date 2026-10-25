from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class EventBus(QObject):
    """Central Qt Signal bus decoupling views, dialogs, and controllers."""

    courses_updated = Signal()
    course_selected = Signal(int)
    notes_updated = Signal(int)  # course_id
    review_session_started = Signal()
    review_session_finished = Signal()
    review_state_changed = Signal()
    status_message = Signal(str, int)  # message, timeout_ms
    navigate_to_tab = Signal(str)  # "courses" | "explorer" | "review" | "browser" | "stats"
    open_node_in_explorer = Signal(int, int)  # course_id, note_id
