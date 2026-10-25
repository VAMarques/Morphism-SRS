from __future__ import annotations

import copy
import json
import sqlite3

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QMimeData, QTimer, QUrl, Qt
from PySide6.QtGui import QCloseEvent, QGuiApplication, QKeyEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from morphism_srs.config import AppConfig
from morphism_srs.domain.enums import NoteReviewMode
from morphism_srs.domain.models import CardModel, NoteModel
from morphism_srs.services.safe_html import sanitize_math_html
from morphism_srs.storage.media_vault import MediaVault
from morphism_srs.storage.repositories.note_repo import NoteRepository
from morphism_srs.storage.unit_of_work import UnitOfWork
from morphism_srs.theming.delegates import set_widget_props
from morphism_srs.ui.components.html_toolbar import HtmlEditorToolbar
from morphism_srs.ui.components.tag_chips import TagChipsWidget
from morphism_srs.ui.window_sizing import (
    apply_relative_geometry,
    configure_splitter,
    wrap_in_scroll_area,
)
from morphism_srs.web_engine.web_profile import WebEngineProfileManager


class MediaPasteTextEdit(QPlainTextEdit):
    """QPlainTextEdit that intercepts Ctrl+V images/SVGs and stores them into MediaVault."""

    def __init__(self, media_vault: MediaVault, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.media_vault = media_vault

    def insertFromMimeData(self, source: QMimeData) -> None:
        if source.hasUrls():
            for url in source.urls():
                if url.isLocalFile():
                    local_path = url.toLocalFile()
                    if local_path.lower().endswith((".svg", ".png", ".webp", ".jpg", ".jpeg", ".gif")):
                        from pathlib import Path
                        _, stored_name = self.media_vault.store_file(Path(local_path))
                        cls_attr = ' class="commutative-diagram"' if stored_name.endswith(".svg") else ""
                        self.insertPlainText(f'<img src="morphism://media/{stored_name}"{cls_attr}>')
                        return

        if source.hasImage():
            image = QGuiApplication.clipboard().image()
            if not image.isNull():
                ba = QByteArray()
                buf = QBuffer(ba)
                buf.open(QIODevice.OpenModeFlag.WriteOnly)
                image.save(buf, "PNG")
                _, stored_name = self.media_vault.store_bytes(bytes(ba), "clipboard.png")
                self.insertPlainText(f'<img src="morphism://media/{stored_name}">')
                return

        if source.hasText():
            txt = source.text().strip()
            if txt.startswith("<svg") and txt.endswith("</svg>"):
                _, stored_name = self.media_vault.store_bytes(txt.encode("utf-8"), "diagram.svg")
                self.insertPlainText(f'<img src="morphism://media/{stored_name}" class="commutative-diagram">')
                return

        super().insertFromMimeData(source)


class NodeEditorDialog(QDialog):
    """
    Prototype 1-style Node & Card Editor:
    - Left column: Attached Cards / Steps list with Move Up/Down, Add, and Delete.
    - Right column: Card Title, Front HTML/LaTeX editor + FlowLayout toolbar,
      Back HTML/LaTeX editor + FlowLayout toolbar, and below them the Live MathJax Preview
      for the currently selected card ONLY.
    -Wrapped in a QScrollArea with non-collapsible splitters and explicit minimum sizes.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        config: AppConfig,
        media_vault: MediaVault,
        web_profile: WebEngineProfileManager,
        course_id: int,
        note: NoteModel | None = None,
        default_pos: tuple[float, float] = (0.0, 0.0),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Note Editor: {note.title}" if note else "Create Mathematical Note")
        apply_relative_geometry(self, width_ratio=0.84, height_ratio=0.86, min_width=860, min_height=580)

        self.conn = conn
        self.config = config
        self.media_vault = media_vault
        self.web_profile = web_profile
        self.course_id = course_id
        self.note_repo = NoteRepository(conn)

        if note is not None:
            self.note = copy.deepcopy(note)
            if not self.note.cards:
                self.note.cards = [
                    CardModel(step_order=0, title="Card 1", front_html="", back_html="")
                ]
        else:
            self.note = NoteModel(
                course_id=course_id,
                title="New Mathematical Note",
                pos_x=default_pos[0],
                pos_y=default_pos[1],
                review_mode=NoteReviewMode.STANDARD,
                cards=[
                    CardModel(
                        step_order=0,
                        title="Card 1",
                        front_html="Write your question here... Use $x^2$ for inline math or $$\\int f(x)\\d x$$ for blocks.",
                        back_html="Write the answer here...",
                    )
                ],
            )

        self._current_editing_row: int = -1
        self._active_text_edit: QPlainTextEdit | None = None
        self._preview_ready = False

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(200)
        self._preview_timer.timeout.connect(self._update_live_preview)

        self._build_ui()
        self._load_note_into_ui()

    def _build_ui(self) -> None:
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        content_container = QWidget(self)
        root = QVBoxLayout(content_container)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        # --- Top Header: Note Title, Review Mode, Retention, Scratchbook ---
        header_row1 = QHBoxLayout()
        header_row1.setSpacing(8)
        header_row1.addWidget(QLabel("<b>Note Title:</b>", content_container))

        self.title_edit = QLineEdit(content_container)
        self.title_edit.setMinimumWidth(200)
        header_row1.addWidget(self.title_edit, 2)

        header_row1.addWidget(QLabel("<b>Review Mode:</b>", content_container))
        self.mode_combo = QComboBox(content_container)
        self.mode_combo.addItem("Standard (Independent Cards)  [Rectangle]", NoteReviewMode.STANDARD.value)
        self.mode_combo.addItem("Serial Sequence (Step-by-step P(A_i | A_j, j<i))  [Diamond]", NoteReviewMode.SERIAL.value)
        self.mode_combo.addItem("Cloze Conditioning (P(A_i | A_j, j≠i))  [Ellipse]", NoteReviewMode.CLOZE.value)
        header_row1.addWidget(self.mode_combo, 1)

        header_row1.addWidget(QLabel("<b>Retention:</b>", content_container))
        self.retention_spin = QDoubleSpinBox(content_container)
        self.retention_spin.setRange(0.70, 0.99)
        self.retention_spin.setSingleStep(0.01)
        self.retention_spin.setValue(self.note.desired_retention or 0.80)
        header_row1.addWidget(self.retention_spin)

        scratch_btn = QPushButton("✏️ Scratchbook", content_container)
        scratch_btn.clicked.connect(self._open_scratchbook)
        header_row1.addWidget(scratch_btn)
        root.addLayout(header_row1)

        # --- Header Row 2: Tags ---
        header_row2 = QHBoxLayout()
        header_row2.setSpacing(8)
        header_row2.addWidget(QLabel("<b>Tags:</b>", content_container))
        all_tags = [t.name for t in self.note_repo.list_all_tags()]
        self.tag_chips = TagChipsWidget(all_tags, content_container)
        header_row2.addWidget(self.tag_chips, 1)
        root.addLayout(header_row2)

        # --- Main Splitter: Left (Card List) vs Right (Card Editors + Single-Card Preview) ---
        main_splitter = QSplitter(Qt.Orientation.Horizontal, content_container)

        # Left Pane: Attached Cards / Steps
        left_pane = QWidget(main_splitter)
        left_layout = QVBoxLayout(left_pane)
        left_layout.setContentsMargins(0, 0, 6, 0)
        left_layout.setSpacing(6)

        steps_lbl = QLabel("<b>Attached Cards / Steps:</b>", left_pane)
        left_layout.addWidget(steps_lbl)

        self.steps_list = QListWidget(left_pane)
        self.steps_list.setMinimumHeight(200)
        self.steps_list.setMinimumWidth(210)
        self.steps_list.currentRowChanged.connect(self._on_step_selected)
        left_layout.addWidget(self.steps_list, 1)

        order_row = QHBoxLayout()
        move_up_btn = QPushButton("▲ Move Up", left_pane)
        move_up_btn.clicked.connect(self._on_move_up)
        move_down_btn = QPushButton("▼ Move Down", left_pane)
        move_down_btn.clicked.connect(self._on_move_down)
        order_row.addWidget(move_up_btn)
        order_row.addWidget(move_down_btn)
        left_layout.addLayout(order_row)

        crud_row = QHBoxLayout()
        add_step_btn = QPushButton("+ Add Card", left_pane)
        set_widget_props(add_step_btn, variant="primary")
        add_step_btn.clicked.connect(self._on_add_step)
        del_step_btn = QPushButton("🗑 Delete", left_pane)
        set_widget_props(del_step_btn, variant="danger")
        del_step_btn.clicked.connect(self._on_remove_step)
        crud_row.addWidget(add_step_btn)
        crud_row.addWidget(del_step_btn)
        left_layout.addLayout(crud_row)

        # Right Pane: Card HTML/LaTeX Editors on top + Live Single-Card Preview on bottom
        right_pane = QWidget(main_splitter)
        right_layout = QVBoxLayout(right_pane)
        right_layout.setContentsMargins(6, 0, 0, 0)
        right_layout.setSpacing(6)

        # Card Title + Save Card Changes + Insert SVG/Image
        card_top_row = QHBoxLayout()
        card_top_row.addWidget(QLabel("<b>Card Title:</b>", right_pane))
        self.card_title_edit = QLineEdit(right_pane)
        self.card_title_edit.setPlaceholderText("e.g. Card 1, Step 1: Base Case...")
        self.card_title_edit.textChanged.connect(self._on_editor_changed)
        card_top_row.addWidget(self.card_title_edit, 1)

        insert_media_btn = QPushButton("🖼 Insert SVG / Image...", right_pane)
        insert_media_btn.clicked.connect(self._on_insert_media_file)
        card_top_row.addWidget(insert_media_btn)

        save_card_btn = QPushButton("💾 Save Card Changes", right_pane)
        save_card_btn.clicked.connect(self._on_manual_save_card)
        card_top_row.addWidget(save_card_btn)
        right_layout.addLayout(card_top_row)

        # Vertical splitter between Editors and Live Preview so neither can collapse to 0
        right_vsplitter = QSplitter(Qt.Orientation.Vertical, right_pane)

        editors_box = QWidget(right_vsplitter)
        editors_layout = QVBoxLayout(editors_box)
        editors_layout.setContentsMargins(0, 0, 0, 4)
        editors_layout.setSpacing(6)

        custom_buttons = self.config.load_editor_buttons()

        # Front Editor + Toolbar
        editors_layout.addWidget(QLabel("<b>Front (HTML & LaTeX):</b>", editors_box))
        self.front_edit = MediaPasteTextEdit(self.media_vault, editors_box)
        self.front_edit.setMinimumHeight(95)
        self.front_edit.textChanged.connect(self._on_editor_changed)
        self._track_focus(self.front_edit)

        self.front_toolbar = HtmlEditorToolbar(
            get_active_editor=lambda: self.front_edit,
            custom_buttons=custom_buttons,
            on_insert_media=lambda: self._on_insert_media_into(self.front_edit),
            bind_shortcuts_to=self.front_edit,
            parent=editors_box,
        )
        editors_layout.addWidget(self.front_toolbar)
        editors_layout.addWidget(self.front_edit, 1)

        # Back Editor + Toolbar
        editors_layout.addWidget(QLabel("<b>Back (HTML & LaTeX):</b>", editors_box))
        self.back_edit = MediaPasteTextEdit(self.media_vault, editors_box)
        self.back_edit.setMinimumHeight(95)
        self.back_edit.textChanged.connect(self._on_editor_changed)
        self._track_focus(self.back_edit)

        self.back_toolbar = HtmlEditorToolbar(
            get_active_editor=lambda: self.back_edit,
            custom_buttons=custom_buttons,
            on_insert_media=lambda: self._on_insert_media_into(self.back_edit),
            bind_shortcuts_to=self.back_edit,
            parent=editors_box,
        )
        editors_layout.addWidget(self.back_toolbar)
        editors_layout.addWidget(self.back_edit, 1)

        # Live Single-Card Preview Box (bottom of right column, just like Prototype 1)
        preview_box = QFrame(right_vsplitter)
        set_widget_props(preview_box, role="panel")
        preview_layout = QVBoxLayout(preview_box)
        preview_layout.setContentsMargins(8, 6, 8, 8)
        preview_layout.setSpacing(4)

        p_header = QLabel("<b>Live Card Preview (MathJax & SVG):</b>", preview_box)
        preview_layout.addWidget(p_header)

        self.web_view = self.web_profile.create_web_view(preview_box)
        self.web_view.setMinimumHeight(200)
        self.web_view.loadFinished.connect(self._on_preview_page_loaded)
        self.web_view.setUrl(QUrl("morphism://app/html/preview.html"))
        preview_layout.addWidget(self.web_view, 1)

        right_vsplitter.addWidget(editors_box)
        right_vsplitter.addWidget(preview_box)
        configure_splitter(right_vsplitter, min_sizes=[260, 210], initial_sizes=[320, 240])
        right_layout.addWidget(right_vsplitter, 1)

        main_splitter.addWidget(left_pane)
        main_splitter.addWidget(right_pane)
        configure_splitter(main_splitter, min_sizes=[230, 540], initial_sizes=[250, 680])
        root.addWidget(main_splitter, 1)

        # Bottom Dialog Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = QPushButton("Cancel", content_container)
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("✅ Save & Close (Ctrl+Enter)", content_container)
        set_widget_props(save_btn, variant="primary")
        save_btn.setMinimumHeight(34)
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        root.addLayout(btn_row)

        scroll = wrap_in_scroll_area(content_container, self, min_width=820, min_height=540)
        outer_layout.addWidget(scroll)

    def _track_focus(self, editor: QPlainTextEdit) -> None:
        orig_focus = editor.focusInEvent

        def _focus_in(ev) -> None:
            self._active_text_edit = editor
            orig_focus(ev)

        editor.focusInEvent = _focus_in  # type: ignore[method-assign]

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and (
            event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self._on_save()
            return
        super().keyPressEvent(event)

    def _load_note_into_ui(self) -> None:
        self.title_edit.setText(self.note.title)
        idx = self.mode_combo.findData(self.note.review_mode.value)
        if idx >= 0:
            self.mode_combo.setCurrentIndex(idx)
        self.tag_chips.set_tags(self.note.tags)
        self._current_editing_row = -1
        self._refresh_steps_list(select_idx=0)

    def _format_step_item_label(self, idx: int, card: CardModel) -> str:
        title_str = card.title.strip() if card.title else f"Card {idx + 1}"
        return f"Step {idx + 1}: {title_str}"

    def _refresh_steps_list(self, select_idx: int = 0) -> None:
        self.steps_list.blockSignals(True)
        self.steps_list.clear()
        for idx, c in enumerate(self.note.cards):
            self.steps_list.addItem(QListWidgetItem(self._format_step_item_label(idx, c)))
        target = max(0, min(select_idx, len(self.note.cards) - 1))
        self.steps_list.setCurrentRow(target)
        self.steps_list.blockSignals(False)

        self._current_editing_row = target
        self._load_card_into_editors(target)

    def _load_card_into_editors(self, idx: int) -> None:
        if not (0 <= idx < len(self.note.cards)):
            return
        c = self.note.cards[idx]
        for w in (self.card_title_edit, self.front_edit, self.back_edit):
            w.blockSignals(True)
        self.card_title_edit.setText(c.title or f"Card {idx + 1}")
        self.front_edit.setPlainText(c.front_html or "")
        self.back_edit.setPlainText(c.back_html or "")
        for w in (self.card_title_edit, self.front_edit, self.back_edit):
            w.blockSignals(False)
        self._preview_timer.start()

    def _sync_current_card_from_editors(self) -> None:
        if not (0 <= self._current_editing_row < len(self.note.cards)):
            return
        c = self.note.cards[self._current_editing_row]
        c.title = self.card_title_edit.text().strip() or f"Card {self._current_editing_row + 1}"
        c.front_html = self.front_edit.toPlainText()
        c.back_html = self.back_edit.toPlainText()
        item = self.steps_list.item(self._current_editing_row)
        if item is not None:
            item.setText(self._format_step_item_label(self._current_editing_row, c))

    def _on_step_selected(self, new_row: int) -> None:
        if not (0 <= new_row < len(self.note.cards)):
            return
        if 0 <= self._current_editing_row < len(self.note.cards) and self._current_editing_row != new_row:
            self._sync_current_card_from_editors()
        self._current_editing_row = new_row
        self._load_card_into_editors(new_row)

    def _on_editor_changed(self) -> None:
        self._sync_current_card_from_editors()
        self._preview_timer.start()

    def _on_manual_save_card(self) -> None:
        self._sync_current_card_from_editors()
        self._update_live_preview()

    def _on_move_up(self) -> None:
        row = self._current_editing_row
        if row <= 0 or row >= len(self.note.cards):
            return
        self._sync_current_card_from_editors()
        self.note.cards[row - 1], self.note.cards[row] = self.note.cards[row], self.note.cards[row - 1]
        for i, c in enumerate(self.note.cards):
            c.step_order = i
        self._refresh_steps_list(select_idx=row - 1)

    def _on_move_down(self) -> None:
        row = self._current_editing_row
        if row < 0 or row >= len(self.note.cards) - 1:
            return
        self._sync_current_card_from_editors()
        self.note.cards[row + 1], self.note.cards[row] = self.note.cards[row], self.note.cards[row + 1]
        for i, c in enumerate(self.note.cards):
            c.step_order = i
        self._refresh_steps_list(select_idx=row + 1)

    def _on_add_step(self) -> None:
        self._sync_current_card_from_editors()
        new_idx = len(self.note.cards)
        self.note.cards.append(
            CardModel(
                step_order=new_idx,
                title=f"Card {new_idx + 1}",
                front_html="Question...",
                back_html="Answer...",
            )
        )
        self._refresh_steps_list(select_idx=new_idx)

    def _on_remove_step(self) -> None:
        if len(self.note.cards) <= 1:
            QMessageBox.information(self, "Cannot Delete", "A note must contain at least one card.")
            return
        self.note.cards.pop(self._current_editing_row)
        for i, c in enumerate(self.note.cards):
            c.step_order = i
        self._refresh_steps_list(select_idx=max(0, self._current_editing_row - 1))

    def _on_insert_media_file(self) -> None:
        target_ed = self._active_text_edit or self.front_edit
        self._on_insert_media_into(target_ed)

    def _on_insert_media_into(self, target_ed: QPlainTextEdit) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Insert SVG or Image into Card",
            "",
            "Diagrams & Images (*.svg *.png *.webp *.jpg *.jpeg *.gif)",
        )
        if not path_str:
            return
        from pathlib import Path
        _, stored = self.media_vault.store_file(Path(path_str))
        cls_attr = ' class="commutative-diagram"' if stored.endswith(".svg") else ""
        target_ed.insertPlainText(f'<img src="morphism://media/{stored}"{cls_attr}>')

    def _open_scratchbook(self) -> None:
        from morphism_srs.ui.dialogs.scratchbook_dialog import ScratchbookDialog
        dlg = ScratchbookDialog(
            conn=self.conn,
            config=self.config,
            web_profile=self.web_profile,
            parent=self,
        )
        dlg.exec()

    def _on_preview_page_loaded(self, ok: bool) -> None:
        self._preview_ready = ok
        if ok:
            self._update_live_preview()

    def _update_live_preview(self) -> None:
        if not self._preview_ready:
            return
        self._sync_current_card_from_editors()
        idx = max(0, min(self._current_editing_row, len(self.note.cards) - 1))
        c = self.note.cards[idx]
        payload = {
            "step_index": idx,
            "card_title": c.title or f"Card {idx + 1}",
            "front_html": c.front_html,
            "back_html": c.back_html,
        }
        self.web_view.page().runJavaScript(
            f"if (window.MorphismPreview && window.MorphismPreview.renderCardPreview) "
            f"{{ window.MorphismPreview.renderCardPreview({json.dumps(payload)}); }}"
        )

    def _on_save(self) -> None:
        self._sync_current_card_from_editors()
        title = self.title_edit.text().strip()
        if not title:
            QMessageBox.warning(self, "Missing Title", "Please enter a title for the note.")
            return

        for idx, c in enumerate(self.note.cards):
            c.step_order = idx
            c.title = c.title.strip() or f"Card {idx + 1}"
            c.hint_html = ""

        self.note.title = title
        self.note.premise_html = ""
        self.note.review_mode = NoteReviewMode(str(self.mode_combo.currentData() or "standard"))
        self.note.desired_retention = self.retention_spin.value()
        self.note.tags = self.tag_chips.tags()

        with UnitOfWork(self.conn):
            if self.note.id is None:
                self.note = self.note_repo.create(self.note)
            else:
                self.note_repo.update(self.note, sync_cards=True)

        self.accept()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.web_profile.dispose_web_view(self.web_view)
        super().closeEvent(event)

    def done(self, result: int) -> None:
        self.web_profile.dispose_web_view(self.web_view)
        super().done(result)
