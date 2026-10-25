from __future__ import annotations

import json
import sqlite3

from PySide6.QtCore import QUrl, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from morphism_srs.controllers.event_bus import EventBus
from morphism_srs.storage.repositories.course_repo import CourseRepository
from morphism_srs.storage.repositories.review_repo import ReviewRepository
from morphism_srs.theming.delegates import set_widget_props
from morphism_srs.ui.window_sizing import configure_splitter, wrap_in_scroll_area
from morphism_srs.web_engine.web_profile import WebEngineProfileManager


class StatsView(QWidget):
    """Statistics Dashboard with 365-Day Review Heatmap and offline Chart.js Forecast & Rating distributions."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        web_profile: WebEngineProfileManager,
        event_bus: EventBus,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.conn = conn
        self.web_profile = web_profile
        self.event_bus = event_bus

        self.course_repo = CourseRepository(conn)
        self.review_repo = ReviewRepository(conn)

        self._heatmap_ready = False
        self._barplot_ready = False

        self._build_ui()
        self.event_bus.courses_updated.connect(self.refresh_stats)
        self.event_bus.review_state_changed.connect(self.refresh_stats)
        self.refresh_stats()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        container = QWidget(self)
        root = QVBoxLayout(container)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(12)

        top_row = QHBoxLayout()
        title = QLabel("Analytics & FSRS v5 Retention Statistics", container)
        set_widget_props(title, role="title")
        top_row.addWidget(title)
        top_row.addStretch(1)

        top_row.addWidget(QLabel("Scope:", container))
        self.scope_combo = QComboBox(container)
        self.scope_combo.setMinimumWidth(200)
        self.scope_combo.currentIndexChanged.connect(lambda _: self.refresh_stats())
        top_row.addWidget(self.scope_combo)

        refresh_btn = QPushButton("Refresh", container)
        set_widget_props(refresh_btn, variant="ghost")
        refresh_btn.clicked.connect(self.refresh_stats)
        top_row.addWidget(refresh_btn)
        root.addLayout(top_row)

        # KPI Cards Row
        kpi_row = QHBoxLayout()
        self.kpi_labels: dict[str, QLabel] = {}
        for key, caption in [
            ("total_cards", "Total Cards"),
            ("due_now", "Due Now"),
            ("total_reviews", "Total Reviews Logged"),
            ("avg_stability", "Mean Stability (S)"),
        ]:
            card = QFrame(container)
            set_widget_props(card, role="card")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(14, 10, 14, 10)
            cap = QLabel(caption, card)
            set_widget_props(cap, role="muted")
            val = QLabel("0", card)
            set_widget_props(val, role="title")
            cl.addWidget(cap)
            cl.addWidget(val)
            self.kpi_labels[key] = val
            kpi_row.addWidget(card, 1)
        root.addLayout(kpi_row)

        charts_splitter = QSplitter(Qt.Orientation.Vertical, container)

        # Heatmap Panel
        hm_frame = QFrame(charts_splitter)
        set_widget_props(hm_frame, role="panel")
        hm_layout = QVBoxLayout(hm_frame)
        hm_layout.setContentsMargins(6, 6, 6, 6)
        self.heatmap_view = self.web_profile.create_web_view(hm_frame)
        self.heatmap_view.setMinimumHeight(145)
        self.heatmap_view.loadFinished.connect(self._on_heatmap_loaded)
        self.heatmap_view.setUrl(QUrl("morphism://app/html/heatmap.html"))
        hm_layout.addWidget(self.heatmap_view, 1)

        # Barplots Panel
        bp_frame = QFrame(charts_splitter)
        set_widget_props(bp_frame, role="panel")
        bp_layout = QVBoxLayout(bp_frame)
        bp_layout.setContentsMargins(6, 6, 6, 6)
        self.barplot_view = self.web_profile.create_web_view(bp_frame)
        self.barplot_view.setMinimumHeight(210)
        self.barplot_view.loadFinished.connect(self._on_barplot_loaded)
        self.barplot_view.setUrl(QUrl("morphism://app/html/barplot.html"))
        bp_layout.addWidget(self.barplot_view, 1)

        charts_splitter.addWidget(hm_frame)
        charts_splitter.addWidget(bp_frame)
        configure_splitter(charts_splitter, min_sizes=[155, 220], initial_sizes=[170, 280])
        root.addWidget(charts_splitter, 1)

        scroll = wrap_in_scroll_area(container, self, min_width=640, min_height=460)
        outer.addWidget(scroll)

        self._reload_scope_combo()

    def _reload_scope_combo(self) -> None:
        self.scope_combo.blockSignals(True)
        self.scope_combo.clear()
        self.scope_combo.addItem("All Courses", None)
        for c in self.course_repo.list_all():
            self.scope_combo.addItem(c.name, c.id)
        self.scope_combo.blockSignals(False)

    def _on_heatmap_loaded(self, ok: bool) -> None:
        self._heatmap_ready = ok
        if ok:
            self.refresh_stats()

    def _on_barplot_loaded(self, ok: bool) -> None:
        self._barplot_ready = ok
        if ok:
            self.refresh_stats()

    def refresh_stats(self) -> None:
        cid = self.scope_combo.currentData()
        course_id = int(cid) if cid is not None else None

        if course_id is None:
            row = self.conn.execute(
                """
                SELECT
                    COUNT(*) AS total_cards,
                    SUM(CASE WHEN is_suspended = 0 AND state > 0 AND due_at <= strftime('%Y-%m-%dT%H:%M:%fZ', 'now') THEN 1 ELSE 0 END) AS due_now,
                    AVG(stability) AS avg_s
                FROM card_schedules;
                """
            ).fetchone()
            rev_row = self.conn.execute("SELECT COUNT(*) AS cnt FROM review_logs;").fetchone()
        else:
            row = self.conn.execute(
                """
                SELECT
                    COUNT(*) AS total_cards,
                    SUM(CASE WHEN cs.is_suspended = 0 AND cs.state > 0 AND cs.due_at <= strftime('%Y-%m-%dT%H:%M:%fZ', 'now') THEN 1 ELSE 0 END) AS due_now,
                    AVG(cs.stability) AS avg_s
                FROM card_schedules cs
                JOIN cards c ON c.id = cs.card_id
                JOIN notes n ON n.id = c.note_id
                WHERE n.course_id = ?;
                """,
                (course_id,),
            ).fetchone()
            rev_row = self.conn.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM review_logs rl
                JOIN cards c ON c.id = rl.card_id
                JOIN notes n ON n.id = c.note_id
                WHERE n.course_id = ?;
                """,
                (course_id,),
            ).fetchone()

        self.kpi_labels["total_cards"].setText(str(int(row["total_cards"] or 0)))
        self.kpi_labels["due_now"].setText(str(int(row["due_now"] or 0)))
        self.kpi_labels["total_reviews"].setText(str(int(rev_row["cnt"] or 0)))
        avg_s = row["avg_s"]
        self.kpi_labels["avg_stability"].setText(f"{float(avg_s):.1f}d" if avg_s is not None else "—")

        if self._heatmap_ready:
            daily_map = self.review_repo.get_daily_review_counts(365)
            self.heatmap_view.page().runJavaScript(
                f"if (window.MorphismCharts) {{ window.MorphismCharts.renderHeatmap({json.dumps(daily_map)}); }}"
            )

        if self._barplot_ready:
            forecast = self.review_repo.get_future_due_forecast(14, course_id=course_id)
            f_labels = list(forecast.keys())
            f_vals = list(forecast.values())
            dist = self.review_repo.get_rating_distribution(course_id=course_id)
            r_counts = [dist.get(1, 0), dist.get(2, 0), dist.get(3, 0), dist.get(4, 0)]
            self.barplot_view.page().runJavaScript(
                f"if (window.MorphismCharts) {{ window.MorphismCharts.renderBarPlots("
                f"{json.dumps(f_labels)}, {json.dumps(f_vals)}, {json.dumps(r_counts)}); }}"
            )
