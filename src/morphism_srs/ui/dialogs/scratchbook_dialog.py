from __future__ import annotations

import json
import sqlite3

from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
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
from morphism_srs.controllers.event_bus import EventBus
from morphism_srs.domain.models import ScratchbookPageModel
from morphism_srs.services.safe_html import sanitize_math_html
from morphism_srs.storage.repositories.scratch_repo import ScratchRepository
from morphism_srs.storage.unit_of_work import UnitOfWork
from morphism_srs.theming.delegates import set_widget_props
from morphism_srs.ui.components.html_toolbar import HtmlEditorToolbar
from morphism_srs.ui.window_sizing import (
    apply_relative_geometry,
    configure_splitter,
    wrap_in_scroll_area,
)
from morphism_srs.web_engine.web_profile import WebEngineProfileManager


DEFAULT_SCRATCH_NOTE = (
    "<h3>Mathematical Scratchpad</h3>\n"
    "Use this space for loose notes, rough calculations, and definitions.<br><br>\n"
    "Inline math: $\\ph : G \\to H$, or display math:\n"
    "$$\\norm{x + y} \\le \\norm{x} + \\norm{y}$$"
)


class ScratchbookDialog(QDialog):
    """Freeform HTML & LaTeX Scratchbook with SQLite page persistence and live MathJax preview."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        web_profile: WebEngineProfileManager,
        event_bus: EventBus | None = None,
        config: AppConfig | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Mathematical Scratchbook")
        apply_relative_geometry(self, width_ratio=0.80, height_ratio=0.80, min_width=780, min_height=520)

        self.conn = conn
        self.config = config or AppConfig()
        self.web_profile = web_profile
        self.event_bus = event_bus
        self.scratch_repo = ScratchRepository(conn)

        self._pages: list[ScratchbookPageModel] = []
        self._current_row: int = -1
        self._preview_ready = False

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(250)
        self._debounce.timeout.connect(self._on_auto_save_and_preview)

        self._build_ui()
        self._load_pages()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        container = QWidget(self)
        root = QVBoxLayout(container)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        top_bar = QHBoxLayout()
        title_lbl = QLabel("✏️ Mathematical Scratchbook (Loose Notes & Drafts)", container)
        set_widget_props(title_lbl, role="title")
        top_bar.addWidget(title_lbl)
        top_bar.addStretch(1)
        root.addLayout(top_bar)

        splitter = QSplitter(Qt.Orientation.Horizontal, container)

        # Left sidebar: Pages list + CRUD buttons
        left_widget = QWidget(splitter)
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 6, 0)
        left_layout.setSpacing(6)

        left_layout.addWidget(QLabel("<b>Scratchbook Pages:</b>", left_widget))

        self.page_list = QListWidget(left_widget)
        self.page_list.setMinimumWidth(190)
        self.page_list.setMinimumHeight(200)
        self.page_list.currentRowChanged.connect(self._on_page_selected)
        left_layout.addWidget(self.page_list, 1)

        page_btns = QHBoxLayout()
        new_btn = QPushButton("+ New", left_widget)
        set_widget_props(new_btn, variant="primary")
        new_btn.clicked.connect(self._on_new_page)

        ren_btn = QPushButton("✏️ Rename", left_widget)
        ren_btn.clicked.connect(self._on_rename_page)

        del_btn = QPushButton("🗑️ Delete", left_widget)
        set_widget_props(del_btn, variant="danger")
        del_btn.clicked.connect(self._on_delete_page)

        page_btns.addWidget(new_btn)
        page_btns.addWidget(ren_btn)
        page_btns.addWidget(del_btn)
        left_layout.addLayout(page_btns)

        # Right area: Vertical splitter with Editor + Toolbar on top and Live MathJax Preview below
        right_vsplitter = QSplitter(Qt.Orientation.Vertical, splitter)

        editor_pane = QWidget(right_vsplitter)
        editor_layout = QVBoxLayout(editor_pane)
        editor_layout.setContentsMargins(4, 0, 0, 4)
        editor_layout.setSpacing(6)

        editor_layout.addWidget(QLabel("<b>Scratchpad (HTML & LaTeX):</b>", editor_pane))

        self.editor = QPlainTextEdit(editor_pane)
        self.editor.setMinimumHeight(130)
        self.editor.setPlaceholderText("Write loose mathematical notes, HTML, or LaTeX ($...$ / $$...$$) here...")
        self.editor.textChanged.connect(lambda: self._debounce.start())

        self.toolbar = HtmlEditorToolbar(
            get_active_editor=lambda: self.editor,
            custom_buttons=self.config.load_editor_buttons(),
            bind_shortcuts_to=self.editor,
            parent=editor_pane,
        )
        editor_layout.addWidget(self.toolbar)
        editor_layout.addWidget(self.editor, 1)

        preview_frame = QFrame(right_vsplitter)
        set_widget_props(preview_frame, role="panel")
        preview_layout = QVBoxLayout(preview_frame)
        preview_layout.setContentsMargins(8, 6, 8, 8)
        preview_layout.setSpacing(4)
        preview_layout.addWidget(QLabel("<b>Live MathJax Preview:</b>", preview_frame))

        self.web_view = self.web_profile.create_web_view(preview_frame)
        self.web_view.setMinimumHeight(190)
        self.web_view.loadFinished.connect(self._on_web_loaded)
        self.web_view.setUrl(QUrl("morphism://app/html/preview.html"))
        preview_layout.addWidget(self.web_view, 1)

        right_vsplitter.addWidget(editor_pane)
        right_vsplitter.addWidget(preview_frame)
        configure_splitter(right_vsplitter, min_sizes=[190, 200], initial_sizes=[250, 250])

        splitter.addWidget(left_widget)
        splitter.addWidget(right_vsplitter)
        configure_splitter(splitter, min_sizes=[210, 500], initial_sizes=[230, 620])
        root.addWidget(splitter, 1)

        bottom_row = QHBoxLayout()
        bottom_row.addStretch(1)
        close_btn = QPushButton("✅ Save & Close", container)
        set_widget_props(close_btn, variant="primary")
        close_btn.setMinimumHeight(32)
        close_btn.clicked.connect(self.accept)
        bottom_row.addWidget(close_btn)
        root.addLayout(bottom_row)

        scroll = wrap_in_scroll_area(container, self, min_width=740, min_height=480)
        outer.addWidget(scroll)

    def _load_pages(self) -> None:
        all_pages = self.scratch_repo.list_all()
        # Clean up any legacy sample .mdsl page if it was auto-created
        cleaned: list[ScratchbookPageModel] = []
        with UnitOfWork(self.conn):
            for p in all_pages:
                if p.title == "Sample .mdsl Deck" or "@course" in (p.content_text or ""):
                    if p.id is not None:
                        self.scratch_repo.delete(p.id)
                else:
                    cleaned.append(p)
            if not cleaned:
                created = self.scratch_repo.create(
                    ScratchbookPageModel(
                        title="General Notes",
                        content_text=DEFAULT_SCRATCH_NOTE,
                        display_order=0,
                    )
                )
                cleaned = [created]

        self._pages = cleaned
        self._current_row = -1

        self.page_list.blockSignals(True)
        self.page_list.clear()
        for p in self._pages:
            self.page_list.addItem(QListWidgetItem(p.title))
        self.page_list.setCurrentRow(0)
        self.page_list.blockSignals(False)

        self._on_page_selected(0)

    def _save_current_page(self) -> None:
        if 0 <= self._current_row < len(self._pages):
            page = self._pages[self._current_row]
            page.content_text = self.editor.toPlainText()
            if page.id is not None:
                with UnitOfWork(self.conn):
                    self.scratch_repo.update(page)

    def _on_page_selected(self, row: int) -> None:
        if not (0 <= row < len(self._pages)):
            return
        if 0 <= self._current_row < len(self._pages) and self._current_row != row:
            self._save_current_page()
        self._current_row = row
        page = self._pages[row]
        self.editor.blockSignals(True)
        self.editor.setPlainText(page.content_text or "")
        self.editor.blockSignals(False)
        self._update_preview()

    def _on_new_page(self) -> None:
        self._save_current_page()
        title, ok = QInputDialog.getText(self, "New Scratchbook Page", "Page Title:", text="New Note")
        if not ok or not title.strip():
            return
        with UnitOfWork(self.conn):
            p = self.scratch_repo.create(
                ScratchbookPageModel(
                    title=title.strip(),
                    content_text="Write your notes here...",
                    display_order=len(self._pages),
                )
            )
        self._pages.append(p)
        self.page_list.addItem(QListWidgetItem(p.title))
        self.page_list.setCurrentRow(len(self._pages) - 1)

    def _on_rename_page(self) -> None:
        if not (0 <= self._current_row < len(self._pages)):
            return
        page = self._pages[self._current_row]
        new_title, ok = QInputDialog.getText(self, "Rename Page", "New Title:", text=page.title)
        if not ok or not new_title.strip():
            return
        page.title = new_title.strip()
        if page.id is not None:
            with UnitOfWork(self.conn):
                self.scratch_repo.update(page)
        item = self.page_list.item(self._current_row)
        if item is not None:
            item.setText(page.title)
        self._update_preview()

    def _on_delete_page(self) -> None:
        if len(self._pages) <= 1 or not (0 <= self._current_row < len(self._pages)):
            QMessageBox.information(self, "Cannot Delete", "You must keep at least one scratchbook page.")
            return
        page = self._pages[self._current_row]
        reply = QMessageBox.question(
            self,
            "Delete Scratchbook Page",
            f"Are you sure you want to delete '{page.title}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if page.id is not None:
            with UnitOfWork(self.conn):
                self.scratch_repo.delete(page.id)
        self._current_row = -1
        self._load_pages()

    def _on_web_loaded(self, ok: bool) -> None:
        self._preview_ready = ok
        if ok:
            self._update_preview()

    def _on_auto_save_and_preview(self) -> None:
        self._save_current_page()
        self._update_preview()

    def _update_preview(self) -> None:
        if not self._preview_ready:
            return
        raw = self.editor.toPlainText()
        title = self._pages[self._current_row].title if (0 <= self._current_row < len(self._pages)) else "Scratchpad"
        payload = {
            "title": title,
            "content_html": raw,
        }
        self.web_view.page().runJavaScript(
            f"if (window.MorphismPreview && window.MorphismPreview.renderScratchPreview) "
            f"{{ window.MorphismPreview.renderScratchPreview({json.dumps(payload)}); }}"
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        self._save_current_page()
        self.web_profile.dispose_web_view(self.web_view)
        super().closeEvent(event)

    def done(self, result: int) -> None:
        self._save_current_page()
        self.web_profile.dispose_web_view(self.web_view)
        super().done(result)
