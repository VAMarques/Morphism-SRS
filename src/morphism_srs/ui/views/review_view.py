from __future__ import annotations

import json
import sqlite3

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from morphism_srs.config import AppConfig
from morphism_srs.controllers.event_bus import EventBus
from morphism_srs.controllers.review_controller import ReviewController
from morphism_srs.domain.enums import RatingEnum
from morphism_srs.storage.media_vault import MediaVault
from morphism_srs.theming.delegates import set_widget_props
from morphism_srs.ui.dialogs.custom_study_dialog import CustomStudyDialog
from morphism_srs.ui.dialogs.node_editor_dialog import NodeEditorDialog
from morphism_srs.ui.dialogs.retrievability_dialog import RetrievabilityDialog
from morphism_srs.ui.window_sizing import wrap_in_scroll_area
from morphism_srs.web_engine.web_profile import WebEngineProfileManager


class ReviewView(QWidget):
    """
    Review View with pre-warmed offline MathJax WebEngine, serial/cloze conditioning,
    FSRS interval previews, keyboard shortcuts (Space, 1-4, E, Ctrl+Z), and Custom Study launcher.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        config: AppConfig,
        media_vault: MediaVault,
        web_profile: WebEngineProfileManager,
        review_controller: ReviewController,
        event_bus: EventBus,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.conn = conn
        self.config = config
        self.media_vault = media_vault
        self.web_profile = web_profile
        self.review_controller = review_controller
        self.event_bus = event_bus

        self._page_ready = False
        self._answer_shown = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._build_ui()
        self.event_bus.review_session_started.connect(self._on_session_updated)
        self.event_bus.review_state_changed.connect(self._on_session_updated)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        container = QWidget(self)
        root = QVBoxLayout(container)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        # Header Bar
        top_bar = QHBoxLayout()
        back_graph_btn = QPushButton("← Graph Explorer", container)
        set_widget_props(back_graph_btn, variant="ghost")
        back_graph_btn.clicked.connect(lambda: self.event_bus.navigate_to_tab.emit("explorer"))
        top_bar.addWidget(back_graph_btn)

        self.course_badge = QLabel("No Active Session", container)
        set_widget_props(self.course_badge, role="badge")
        top_bar.addWidget(self.course_badge)

        self.progress_label = QLabel("0 / 0 remaining", container)
        set_widget_props(self.progress_label, role="muted")
        top_bar.addWidget(self.progress_label)
        top_bar.addStretch(1)

        self.metrics_btn = QPushButton("📈 R(t) Metrics", container)
        set_widget_props(self.metrics_btn, variant="ghost")
        self.metrics_btn.clicked.connect(self._on_open_metrics)
        top_bar.addWidget(self.metrics_btn)

        self.edit_btn = QPushButton("✏️ Edit Note (E)", container)
        set_widget_props(self.edit_btn, variant="ghost")
        self.edit_btn.clicked.connect(self._on_edit_current_note)
        top_bar.addWidget(self.edit_btn)

        self.undo_btn = QPushButton("↩ Undo (Ctrl+Z)", container)
        set_widget_props(self.undo_btn, variant="ghost")
        self.undo_btn.clicked.connect(self._on_undo)
        top_bar.addWidget(self.undo_btn)

        custom_btn = QPushButton("Custom Study...", container)
        set_widget_props(custom_btn, variant="ghost")
        custom_btn.clicked.connect(self._on_open_custom_study)
        top_bar.addWidget(custom_btn)

        auto_btn = QPushButton("Auto-Study Due", container)
        set_widget_props(auto_btn, variant="ghost")
        auto_btn.setToolTip("Secondary mode: queue due cards across courses (Primary workflow is studying nodes in Graph Explorer)")
        auto_btn.clicked.connect(self._on_start_auto_study)
        top_bar.addWidget(auto_btn)

        root.addLayout(top_bar)

        # WebEngine Card Viewport
        card_frame = QFrame(container)
        set_widget_props(card_frame, role="panel")
        card_frame.setMinimumHeight(280)
        cf_layout = QVBoxLayout(card_frame)
        cf_layout.setContentsMargins(2, 2, 2, 2)
        self.web_view = self.web_profile.create_web_view(card_frame)
        self.web_view.setMinimumHeight(260)
        self.web_view.loadFinished.connect(self._on_web_loaded)
        self.web_view.setUrl(QUrl("morphism://app/html/review.html"))
        cf_layout.addWidget(self.web_view, 1)
        root.addWidget(card_frame, 1)

        # Bottom Action Bar (Show Answer / 4 Rating Buttons)
        bottom_bar = QHBoxLayout()
        self.show_answer_btn = QPushButton("Show Answer (Space)", container)
        set_widget_props(self.show_answer_btn, variant="primary")
        self.show_answer_btn.setMinimumHeight(40)
        self.show_answer_btn.clicked.connect(self._on_reveal_answer)
        bottom_bar.addWidget(self.show_answer_btn)

        self.rating_container = QWidget(container)
        r_layout = QHBoxLayout(self.rating_container)
        r_layout.setContentsMargins(0, 0, 0, 0)
        r_layout.setSpacing(10)

        self.btn_again = QPushButton("Again (1)", self.rating_container)
        set_widget_props(self.btn_again, rating="again")
        self.btn_again.setMinimumHeight(40)
        self.btn_again.clicked.connect(lambda: self._on_rate(RatingEnum.AGAIN))

        self.btn_hard = QPushButton("Hard (2)", self.rating_container)
        set_widget_props(self.btn_hard, rating="hard")
        self.btn_hard.setMinimumHeight(40)
        self.btn_hard.clicked.connect(lambda: self._on_rate(RatingEnum.HARD))

        self.btn_good = QPushButton("Good (3)", self.rating_container)
        set_widget_props(self.btn_good, rating="good")
        self.btn_good.setMinimumHeight(40)
        self.btn_good.clicked.connect(lambda: self._on_rate(RatingEnum.GOOD))

        self.btn_easy = QPushButton("Easy (4)", self.rating_container)
        set_widget_props(self.btn_easy, rating="easy")
        self.btn_easy.setMinimumHeight(40)
        self.btn_easy.clicked.connect(lambda: self._on_rate(RatingEnum.EASY))

        r_layout.addWidget(self.btn_again, 1)
        r_layout.addWidget(self.btn_hard, 1)
        r_layout.addWidget(self.btn_good, 1)
        r_layout.addWidget(self.btn_easy, 1)
        self.rating_container.setVisible(False)
        bottom_bar.addWidget(self.rating_container, 1)

        root.addLayout(bottom_bar)

        scroll = wrap_in_scroll_area(container, self, min_width=640, min_height=420)
        outer.addWidget(scroll)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if (event.modifiers() & Qt.KeyboardModifier.ControlModifier) and event.key() == Qt.Key.Key_Z:
            self._on_undo()
            return
        if event.key() == Qt.Key.Key_Space or event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not self._answer_shown:
                self._on_reveal_answer()
            else:
                self._on_rate(RatingEnum.GOOD)
            return
        if self._answer_shown:
            if event.key() == Qt.Key.Key_1:
                self._on_rate(RatingEnum.AGAIN)
                return
            if event.key() == Qt.Key.Key_2:
                self._on_rate(RatingEnum.HARD)
                return
            if event.key() == Qt.Key.Key_3:
                self._on_rate(RatingEnum.GOOD)
                return
            if event.key() == Qt.Key.Key_4:
                self._on_rate(RatingEnum.EASY)
                return
        if event.key() == Qt.Key.Key_E:
            self._on_edit_current_note()
            return
        super().keyPressEvent(event)

    def _on_web_loaded(self, ok: bool) -> None:
        self._page_ready = ok
        if ok:
            self._render_current_card()

    def _on_start_auto_study(self) -> None:
        count = self.review_controller.start_auto_study()
        if count == 0:
            QMessageBox.information(self, "All Caught Up", "There are no Due or New cards across your courses right now!")
        self._on_session_updated()

    def _on_open_custom_study(self) -> None:
        dlg = CustomStudyDialog(self.conn, parent=self)
        if dlg.exec():
            cfg = dlg.build_config()
            count = self.review_controller.start_custom_study(cfg)
            if count == 0:
                QMessageBox.information(self, "Empty Queue", "No cards matched your Custom Study criteria.")
            self._on_session_updated()

    def _on_session_updated(self) -> None:
        self._answer_shown = False
        self._render_current_card()

    def _render_current_card(self) -> None:
        self.undo_btn.setEnabled(self.review_controller.undo_stack.can_undo())
        ctx = self.review_controller.current_prompt_context()

        if ctx is None:
            self.course_badge.setText("Session Complete")
            self.progress_label.setText("0 remaining")
            self.show_answer_btn.setVisible(False)
            self.rating_container.setVisible(False)
            if self._page_ready:
                empty_payload = {
                    "note_title": "Session Complete!",
                    "review_mode": "standard",
                    "tags": [],
                    "siblings": [],
                    "step_order": 0,
                    "card_title": "",
                    "front_html": (
                        "All cards in this study queue have been reviewed.<br><br>"
                        "Click <b>← Graph Explorer</b> above to select the next node in your course DAG."
                    ),
                    "back_html": "",
                    "show_answer": False,
                }
                self.web_view.page().runJavaScript(
                    f"if (window.MorphismReview) {{ window.MorphismReview.renderCardState({json.dumps(empty_payload)}); }}"
                )
            return

        sandbox_tag = " [CRAM SANDBOX]" if self.review_controller.is_cram_sandbox else ""
        self.course_badge.setText(f"{ctx.course_name}{sandbox_tag}")
        self.progress_label.setText(
            f"Card {self.review_controller.current_Index_1based()} of {self.review_controller.total_count()} "
            f"({self.review_controller.remaining_count()} left)"
        )

        iv = ctx.intervals_preview
        self.btn_again.setText(f"Again (1) • {iv.get(1, '<1m')}")
        self.btn_hard.setText(f"Hard (2) • {iv.get(2, '10m')}")
        self.btn_good.setText(f"Good (3) • {iv.get(3, '1d')}")
        self.btn_easy.setText(f"Easy (4) • {iv.get(4, '4d')}")

        self.show_answer_btn.setVisible(not self._answer_shown)
        self.rating_container.setVisible(self._answer_shown)

        if self._page_ready:
            payload = {
                "note_title": ctx.note.title,
                "review_mode": ctx.review_mode.value,
                "tags": ctx.note.tags,
                "siblings": [
                    {
                        "step_order": s.step_order,
                        "title": s.title,
                        "front_html": s.front_html,
                        "back_html": s.back_html,
                        "position": s.position,
                    }
                    for s in ctx.conditioning_siblings
                ],
                "step_order": ctx.card.step_order,
                "card_title": ctx.card.title,
                "front_html": ctx.card.front_html,
                "back_html": ctx.card.back_html,
                "show_answer": self._answer_shown,
            }
            self.web_view.page().runJavaScript(
                f"if (window.MorphismReview) {{ window.MorphismReview.renderCardState({json.dumps(payload)}); }}"
            )
        self.setFocus()

    def _on_reveal_answer(self) -> None:
        ctx = self.review_controller.current_prompt_context()
        if ctx is None:
            return
        self._answer_shown = True
        self.show_answer_btn.setVisible(False)
        self.rating_container.setVisible(True)
        if self._page_ready:
            self.web_view.page().runJavaScript(
                f"if (window.MorphismReview) {{ window.MorphismReview.revealAnswer({json.dumps(ctx.card.back_html)}); }}"
            )
        self.setFocus()

    def _on_rate(self, rating: RatingEnum) -> None:
        self.review_controller.submit_rating(rating)

    def _on_undo(self) -> None:
        msg = self.review_controller.undo_last_review()
        if msg:
            self._answer_shown = True
            self._render_current_card()

    def _on_edit_current_note(self) -> None:
        ctx = self.review_controller.current_prompt_context()
        if ctx is None:
            return
        dlg = NodeEditorDialog(
            conn=self.conn,
            config=self.config,
            media_vault=self.media_vault,
            web_profile=self.web_profile,
            course_id=ctx.note.course_id,
            note=ctx.note,
            parent=self,
        )
        if dlg.exec():
            self.event_bus.notes_updated.emit(ctx.note.course_id)
            self._render_current_card()

    def _on_open_metrics(self) -> None:
        ctx = self.review_controller.current_prompt_context()
        if ctx is None or ctx.note.id is None:
            return
        dlg = RetrievabilityDialog(self.conn, self.web_profile, ctx.note.id, parent=self)
        dlg.exec()
