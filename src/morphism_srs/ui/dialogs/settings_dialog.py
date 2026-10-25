from __future__ import annotations

import json
import sqlite3

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from morphism_srs.config import AppConfig
from morphism_srs.domain.scheduler_engine import SchedulerEngine
from morphism_srs.storage.repositories.card_repo import CardRepository
from morphism_srs.storage.repositories.folder_repo import FolderRepository
from morphism_srs.storage.repositories.review_repo import ReviewRepository
from morphism_srs.storage.unit_of_work import UnitOfWork
from morphism_srs.theming.delegates import set_widget_props
from morphism_srs.theming.theme_manager import ThemeManager
from morphism_srs.ui.window_sizing import apply_relative_geometry, wrap_in_scroll_area


class SettingsDialog(QDialog):
    """Settings Dialog for Theme hot-reloading, FSRS Global/Folder optimization, and MathJax Macros."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        config: AppConfig,
        theme_manager: ThemeManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Morphism SRS Settings")
        apply_relative_geometry(self, width_ratio=0.58, height_ratio=0.68, min_width=580, min_height=450)

        self.conn = conn
        self.config = config
        self.theme_manager = theme_manager
        self.folder_repo = FolderRepository(conn)
        self.card_repo = CardRepository(conn)
        self.review_repo = ReviewRepository(conn)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        container = QWidget(self)
        root = QVBoxLayout(container)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        self.tabs = QTabWidget(container)
        self.tabs.addTab(self._build_general_tab(), "Appearance & General")
        self.tabs.addTab(self._build_fsrs_tab(), "FSRS v5 & Rescheduling")
        self.tabs.addTab(self._build_macros_tab(), "LaTeX Macros & Snippets")
        root.addWidget(self.tabs, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = QPushButton("Cancel", container)
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Save & Apply", container)
        set_widget_props(save_btn, variant="primary")
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        root.addLayout(btn_row)

        scroll = wrap_in_scroll_area(container, self, min_width=540, min_height=410)
        outer.addWidget(scroll)

    def _build_general_tab(self) -> QWidget:
        w = QWidget(self)
        form = QFormLayout(w)
        form.setSpacing(10)

        self.theme_combo = QComboBox(w)
        for tid, tname in self.theme_manager.available_themes():
            self.theme_combo.addItem(tname, tid)
        idx = self.theme_combo.findData(self.theme_manager.current_theme_id)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        self.theme_combo.currentIndexChanged.connect(self._on_preview_theme)
        form.addRow("Active UI Theme:", self.theme_combo)

        self.retention_spin = QDoubleSpinBox(w)
        self.retention_spin.setRange(0.70, 0.99)
        self.retention_spin.setSingleStep(0.01)
        self.retention_spin.setValue(float(self.config.get("default_desired_retention", 0.80)))
        form.addRow("Default Desired Retention:", self.retention_spin)

        self.backups_spin = QSpinBox(w)
        self.backups_spin.setRange(1, 50)
        self.backups_spin.setValue(int(self.config.get("max_backups", 10)))
        form.addRow("Max Automatic SQLite Backups:", self.backups_spin)
        return w

    def _build_fsrs_tab(self) -> QWidget:
        w = QWidget(self)
        layout = QVBoxLayout(w)
        layout.setSpacing(10)

        form = QFormLayout()
        self.scope_combo = QComboBox(w)
        self.scope_combo.addItem("Global (All Courses)", None)
        for f in self.folder_repo.list_all():
            self.scope_combo.addItem(f"Folder: {f.name}", f.id)
        self.scope_combo.currentIndexChanged.connect(self._load_scope_weights)
        form.addRow("Optimization Scope:", self.scope_combo)
        layout.addLayout(form)

        lbl = QLabel("FSRS v5 Parameter Weights (JSON array of 19 floats, or empty to inherit):", w)
        set_widget_props(lbl, role="muted")
        layout.addWidget(lbl)

        self.weights_edit = QPlainTextEdit(w)
        self.weights_edit.setMinimumHeight(80)
        layout.addWidget(self.weights_edit)
        self._load_scope_weights()

        resched_btn = QPushButton("Replay Review Logs & Reschedule Cards in Scope", w)
        resched_btn.clicked.connect(self._on_reschedule_scope)
        layout.addWidget(resched_btn)
        layout.addStretch(1)
        return w

    def _build_macros_tab(self) -> QWidget:
        w = QWidget(self)
        layout = QVBoxLayout(w)
        layout.setSpacing(8)

        lbl = QLabel("Global MathJax LaTeX Macros (mathjax_macros.json):", w)
        set_widget_props(lbl, role="subtitle")
        layout.addWidget(lbl)

        self.macros_edit = QPlainTextEdit(w)
        self.macros_edit.setMinimumHeight(180)
        self.macros_edit.setPlainText(json.dumps(self.config.load_mathjax_macros(), indent=2, ensure_ascii=False))
        layout.addWidget(self.macros_edit, 1)
        return w

    def _on_preview_theme(self) -> None:
        tid = str(self.theme_combo.currentData() or "dark_slate")
        self.theme_manager.apply_theme(tid)

    def _load_scope_weights(self) -> None:
        fid = self.scope_combo.currentData()
        if fid is None:
            w_str = self.folder_repo.resolve_effective_fsrs_weights(None) or ""
        else:
            folder = self.folder_repo.get_by_id(int(fid))
            w_str = (folder.fsrs_weights_json or "") if folder else ""
        self.weights_edit.setPlainText(w_str)

    def _save_scope_weights(self) -> bool:
        raw = self.weights_edit.toPlainText().strip()
        if raw:
            try:
                parsed = json.loads(raw)
                if not isinstance(parsed, list) or len(parsed) not in (17, 19):
                    QMessageBox.warning(self, "Invalid FSRS Weights", "FSRS weights must be a JSON array of 17 or 19 numbers.")
                    return False
            except Exception as exc:
                QMessageBox.warning(self, "Invalid JSON", str(exc))
                return False

        fid = self.scope_combo.currentData()
        with UnitOfWork(self.conn):
            if fid is None:
                if raw:
                    self.folder_repo.set_global_fsrs_weights(raw)
            else:
                folder = self.folder_repo.get_by_id(int(fid))
                if folder:
                    folder.fsrs_weights_json = raw or None
                    self.folder_repo.update(folder)
        return True

    def _on_reschedule_scope(self) -> None:
        if not self._save_scope_weights():
            return
        fid = self.scope_combo.currentData()
        weights = self.folder_repo.resolve_effective_fsrs_weights(int(fid) if fid is not None else None)
        engine = SchedulerEngine(desired_retention=self.retention_spin.value(), weights_json=weights)

        rows = self.conn.execute("SELECT id FROM cards;").fetchall()
        count = 0
        with UnitOfWork(self.conn):
            for r in rows:
                cid = int(r["id"])
                logs = self.review_repo.list_logs_for_card(cid)
                if logs:
                    card = self.card_repo.get_by_id(cid)
                    new_sched = engine.reschedule_from_logs(cid, logs, card.schedule if card else None)
                    self.card_repo.update_schedule(new_sched)
                    count += 1
        QMessageBox.information(self, "Reschedule Complete", f"Replayed review history for {count} reviewed card(s).")

    def _on_save(self) -> None:
        if not self._save_scope_weights():
            return
        try:
            macros_obj = json.loads(self.macros_edit.toPlainText().strip() or "{}")
            if isinstance(macros_obj, dict):
                self.config.save_mathjax_macros(macros_obj)
        except Exception as exc:
            QMessageBox.warning(self, "Invalid Macros JSON", f"Could not parse MathJax macros JSON:\n{exc}")
            return

        tid = str(self.theme_combo.currentData() or "dark_slate")
        self.config.set("theme", tid)
        self.config.set("default_desired_retention", self.retention_spin.value())
        self.config.set("max_backups", self.backups_spin.value())
        self.theme_manager.apply_theme(tid)
        self.accept()
