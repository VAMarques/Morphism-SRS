from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import sqlite3

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from morphism_srs.domain.scheduler_engine import SchedulerEngine
from morphism_srs.storage.repositories.note_repo import NoteRepository
from morphism_srs.theming.delegates import set_widget_props
from morphism_srs.ui.window_sizing import (
    apply_relative_geometry,
    configure_splitter,
    wrap_in_scroll_area,
)
from morphism_srs.web_engine.web_profile import WebEngineProfileManager


class RetrievabilityDialog(QDialog):
    """Displays Note-level and Card-level FSRS v5 metrics: Bottleneck R_min, Mean R_avg, and Joint Retrieval P(∩ A_i)."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        web_profile: WebEngineProfileManager,
        note_id: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Mathematical Retrievability Inspector")
        apply_relative_geometry(self, width_ratio=0.70, height_ratio=0.76, min_width=700, min_height=500)

        self.conn = conn
        self.web_profile = web_profile
        self.note_repo = NoteRepository(conn)
        self.note = self.note_repo.get_by_id(note_id, include_children=True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        container = QWidget(self)
        root = QVBoxLayout(container)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        note_title = self.note.title if self.note else f"Note #{note_id}"
        header = QLabel(f"📈 Retrievability Breakdown — {note_title}", container)
        set_widget_props(header, role="title")
        root.addWidget(header)

        scheds = [c.schedule for c in (self.note.cards if self.note else []) if c.schedule is not None]
        metrics = SchedulerEngine.compute_note_metrics(note_id, scheds)

        kpi_row = QHBoxLayout()
        for label_str, val_str in [
            ("Bottleneck R_min", f"{metrics.r_min * 100:.1f}%"),
            ("Mean R_avg", f"{metrics.r_avg * 100:.1f}%"),
            ("Joint Retrieval P(∩ A_i)", f"{metrics.p_joint * 100:.1f}%"),
            ("Total Steps / Cards", str(metrics.card_count)),
        ]:
            card_frame = QFrame(container)
            set_widget_props(card_frame, role="card")
            fl = QVBoxLayout(card_frame)
            fl.setContentsMargins(12, 8, 12, 8)
            k_lbl = QLabel(label_str, card_frame)
            set_widget_props(k_lbl, role="muted")
            v_lbl = QLabel(val_str, card_frame)
            set_widget_props(v_lbl, role="title")
            fl.addWidget(k_lbl)
            fl.addWidget(v_lbl)
            kpi_row.addWidget(card_frame, 1)
        root.addLayout(kpi_row)

        vsplitter = QSplitter(Qt.Orientation.Vertical, container)

        self.web_view = self.web_profile.create_web_view(vsplitter)
        self.web_view.setMinimumHeight(220)
        self.web_view.loadFinished.connect(self._on_chart_loaded)
        self.web_view.setUrl(QUrl("morphism://app/html/decay_chart.html"))

        self.table = QTableWidget(vsplitter)
        self.table.setMinimumHeight(140)
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["Step", "Title", "State", "Stability (S)", "Difficulty (D)", "Current R(t)"])
        cards = self.note.cards if self.note else []
        self.table.setRowCount(len(cards))
        now_dt = datetime.now(timezone.utc)
        for row_idx, c in enumerate(cards):
            s = c.schedule
            r_val = SchedulerEngine.compute_card_retrievability(s, now_dt) if s else 0.0
            self.table.setItem(row_idx, 0, QTableWidgetItem(str(c.step_order + 1)))
            self.table.setItem(row_idx, 1, QTableWidgetItem(c.title or f"Step {c.step_order + 1}"))
            self.table.setItem(row_idx, 2, QTableWidgetItem(s.state.name if s else "NEW"))
            self.table.setItem(row_idx, 3, QTableWidgetItem(f"{s.stability:.2f}d" if (s and s.stability) else "—"))
            self.table.setItem(row_idx, 4, QTableWidgetItem(f"{s.difficulty:.2f}" if (s and s.difficulty) else "—"))
            self.table.setItem(row_idx, 5, QTableWidgetItem(f"{r_val * 100:.1f}%"))
        self.table.resizeColumnsToContents()

        vsplitter.addWidget(self.web_view)
        vsplitter.addWidget(self.table)
        configure_splitter(vsplitter, min_sizes=[220, 140], initial_sizes=[260, 160])
        root.addWidget(vsplitter, 1)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_btn = QPushButton("Close", container)
        close_btn.setMinimumHeight(32)
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        root.addLayout(close_row)

        scroll = wrap_in_scroll_area(container, self, min_width=640, min_height=460)
        outer.addWidget(scroll)

    def _on_chart_loaded(self, ok: bool) -> None:
        if not ok or not self.note:
            return
        scheds = [c.schedule for c in self.note.cards if c.schedule is not None]
        now_dt = datetime.now(timezone.utc)
        labels: list[str] = []
        r_min_list: list[float] = []
        r_avg_list: list[float] = []
        p_joint_list: list[float] = []

        for day in range(0, 31):
            sim_dt = now_dt + timedelta(days=day)
            m = SchedulerEngine.compute_note_metrics(self.note.id or 0, scheds, sim_dt)
            labels.append(f"+{day}d")
            r_min_list.append(round(m.r_min * 100.0, 2))
            r_avg_list.append(round(m.r_avg * 100.0, 2))
            p_joint_list.append(round(m.p_joint * 100.0, 2))

        js = (
            f"if (window.MorphismCharts) {{ window.MorphismCharts.renderDecayCurves("
            f"{json.dumps(labels)}, {json.dumps(r_min_list)}, {json.dumps(r_avg_list)}, {json.dumps(p_joint_list)}); }}"
        )
        self.web_view.page().runJavaScript(js)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.web_profile.dispose_web_view(self.web_view)
        super().closeEvent(event)

    def done(self, result: int) -> None:
        self.web_profile.dispose_web_view(self.web_view)
        super().done(result)
