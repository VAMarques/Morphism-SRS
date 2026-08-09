import json
import os
from typing import Optional, List, Dict
from datetime import datetime, timezone, timedelta
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                               QComboBox, QPushButton, QGroupBox, QTableWidget, 
                               QTableWidgetItem, QHeaderView, QSplitter, QScrollArea, QWidget)

from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QIcon
from models import Course, NoteNode, ReviewLogRecord, to_hex_id

from scheduler_manager import SchedulerManager
import course_storage

ASSETS_DIR = os.path.abspath("assets").replace("\\", "/")

CHART_JS_PATH = os.path.join(os.path.abspath("assets"), "chart.js")
CHART_JS_CODE = ""
if os.path.exists(CHART_JS_PATH):
    with open(CHART_JS_PATH, "r", encoding="utf-8") as f:
        CHART_JS_CODE = f.read()

CHART_HTML_TEMPLATE = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <script>
    {CHART_JS_CODE}
    </script>
    <style>
        body {{
            background-color: #0f172a;
            color: #f8fafc;
            font-family: -apple-system, sans-serif;
            margin: 0;
            padding: 12px;
        }}
        .container {{
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 10px;
            padding: 14px;
        }}
        h2 {{
            color: #38bdf8;
            margin-top: 0;
            font-size: 17px;
        }}
        .canvas-holder {{
            position: relative;
            height: 380px;
            width: 100%;
        }}


    </style>
    <script>
        let myChart = null;

        window.renderChart = function(title, labels, datasets) {{
            let titleEl = document.getElementById('chart-title');
            if (titleEl) titleEl.innerText = title;
            let canvas = document.getElementById('retrievabilityChart');
            if (!canvas || typeof Chart === 'undefined') return;
            let ctx = canvas.getContext('2d');
            
            if (myChart) {{
                myChart.destroy();
            }}

            myChart = new Chart(ctx, {{
                type: 'line',
                data: {{
                    labels: labels,
                    datasets: datasets
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {{
                        x: {{
                            grid: {{ color: '#334155' }},
                            ticks: {{ color: '#94a3b8' }},
                            title: {{ display: true, text: 'Days from Today (t)', color: '#94a3b8' }}
                        }},
                        y: {{
                            min: 0,
                            max: 100,
                            grid: {{ color: '#334155' }},
                            ticks: {{ color: '#94a3b8', callback: value => value + '%' }},
                            title: {{ display: true, text: 'Retrievability R(t)', color: '#94a3b8' }}
                        }}
                    }},
                    plugins: {{
                        legend: {{
                            labels: {{ color: '#f8fafc', font: {{ size: 12 }} }}
                        }},
                        tooltip: {{
                            mode: 'index',
                            intersect: false
                        }}
                    }}
                }}
            }});
        }};
    </script>
</head>
<body>
    <div class="container">
        <h2 id="chart-title">Retrievability Decay R(t) Over Time</h2>
        <div class="canvas-holder">
            <canvas id="retrievabilityChart"></canvas>
        </div>
    </div>
</body>
</html>
"""

class RetrievabilityPlotDialog(QDialog):
    """Dialog for inspecting Note retrievability metrics, per-card breakdown, decay chart, and review history."""

    def __init__(self, course: Course, scheduler_manager: SchedulerManager, initial_note: Optional[NoteNode] = None, parent=None):
        super().__init__(parent)
        self.course = course
        self.scheduler_manager = scheduler_manager
        self.initial_note = initial_note
        self.is_page_loaded = False

        if os.path.exists("icon.ico"):
            self.setWindowIcon(QIcon("icon.ico"))

        self.setWindowTitle(f"📈 Note Info & Retrievability Plotter - {course.name}")
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint | Qt.WindowMinimizeButtonHint)
        self.setMinimumSize(840, 560)
        self.resize(1080, 720)
        self._setup_ui()
        self._load_notes_list()


    def _setup_ui(self):
        main_layout = QVBoxLayout(self)

        # Header Selector Bar
        header_layout = QHBoxLayout()
        header_layout.addWidget(QLabel("Select Note:"))
        self.combo_notes = QComboBox()
        self.combo_notes.currentIndexChanged.connect(self._on_note_selected)
        header_layout.addWidget(self.combo_notes, stretch=2)

        header_layout.addSpacing(16)
        header_layout.addWidget(QLabel("Time Scale / Zoom:"))
        self.combo_scale = QComboBox()
        self.combo_scale.addItem("🔍 24 Hours (Intraday Zoom)", "24h")
        self.combo_scale.addItem("🔍 48 Hours (2-Day Zoom)", "48h")
        self.combo_scale.addItem("🔍 7 Days (Weekly Zoom)", "7d")
        self.combo_scale.addItem("🔍 30 Days (Monthly View)", "30d")
        self.combo_scale.addItem("🔍 90 Days (Quarterly View)", "90d")
        self.combo_scale.setCurrentIndex(0)  # Default to 24 Hours Zoom
        self.combo_scale.currentIndexChanged.connect(self._on_note_selected)
        header_layout.addWidget(self.combo_scale, stretch=1)

        main_layout.addLayout(header_layout)


        # Summary Header Badge
        self.lbl_note_summary = QLabel()
        self.lbl_note_summary.setStyleSheet("background-color: #1e293b; border: 1px solid #334155; padding: 10px 16px; border-radius: 8px; font-size: 14px; font-weight: bold; color: #38bdf8;")
        main_layout.addWidget(self.lbl_note_summary)

        # Scroll Area Container for Constant-Sized Elements
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(16)

        # 1. Top Section: Retrievability Decay Line Chart
        chart_group = QGroupBox("Retrievability Decay Curves R(t)")
        chart_layout = QVBoxLayout(chart_group)

        self.browser = QWebEngineView()
        self.browser.setMinimumHeight(320)
        self.browser.setHtml(CHART_HTML_TEMPLATE, QUrl.fromLocalFile(ASSETS_DIR + "/"))
        self.browser.loadFinished.connect(self._on_page_loaded)
        chart_layout.addWidget(self.browser)
        scroll_layout.addWidget(chart_group)

        # 2. Middle Section: Per-card Breakdown Table
        cards_group = QGroupBox("Current Retrievability (Per-Card Breakdown)")
        cards_layout = QVBoxLayout(cards_group)

        self.table_cards = QTableWidget()
        self.table_cards.setMinimumHeight(220)
        self.table_cards.setColumnCount(5)
        self.table_cards.setHorizontalHeaderLabels(["Card / Step", "Retrievability R(now)", "Stability (S)", "Difficulty (D)", "Status"])
        self.table_cards.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        cards_layout.addWidget(self.table_cards)
        scroll_layout.addWidget(cards_group)

        # 3. Bottom Section: Historical Review Logs Table
        history_group = QGroupBox("Historical Reviews Log")
        history_layout = QVBoxLayout(history_group)

        self.table_history = QTableWidget()
        self.table_history.setMinimumHeight(240)
        self.table_history.setColumnCount(4)
        self.table_history.setHorizontalHeaderLabels(["Card ID", "Rating", "Review Date & Time", "Interval"])
        self.table_history.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        history_layout.addWidget(self.table_history)
        scroll_layout.addWidget(history_group)

        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area, stretch=1)

        # Bottom Close Button
        bottom_layout = QHBoxLayout()
        bottom_layout.addStretch()
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        bottom_layout.addWidget(btn_close)
        main_layout.addLayout(bottom_layout)


    def _on_page_loaded(self, ok: bool):
        self.is_page_loaded = True
        self._plot_current_note()

    def _load_notes_list(self):
        self.combo_notes.clear()
        target_idx = 0
        for idx, note in enumerate(self.course.notes):
            self.combo_notes.addItem(f"{note.title} ({len(note.cards)} cards)", note)
            if self.initial_note and note.note_id == self.initial_note.note_id:
                target_idx = idx

        if self.course.notes:
            self.combo_notes.setCurrentIndex(target_idx)
            self._plot_current_note()

    def _on_note_selected(self):
        self._plot_current_note()

    def _get_continuous_card_retrievability(self, card, target_dt: datetime) -> float:

        """
        Calculate continuous power-law retrievability R(t) in [0.0, 1.0] for info graph display.
        Uses fractional elapsed days (total_seconds / 86400.0) to prevent PyFSRS integer day truncation.
        """
        fc = card.fsrs_card if hasattr(card, "fsrs_card") else card
        if fc.last_review is None or fc.stability is None or fc.stability <= 0:
            return 0.0
        elapsed_seconds = (target_dt - fc.last_review).total_seconds()
        if elapsed_seconds < 0:
            return 1.0
        elapsed_days = elapsed_seconds / 86400.0
        factor = getattr(self.scheduler_manager.scheduler, "_FACTOR", 19.0 / 81.0)
        decay = getattr(self.scheduler_manager.scheduler, "_DECAY", -0.5)
        r = (1.0 + factor * elapsed_days / fc.stability) ** decay
        return max(0.0, min(1.0, float(r)))

    def _plot_current_note(self):

        note: NoteNode = self.combo_notes.currentData()
        if not note:
            return

        now_dt = datetime.now(timezone.utc)
        joint_r = note.get_joint_retention(self.scheduler_manager)
        joint_pct = round(joint_r * 100, 1)
        target_pct = round(note.desired_retention * 100, 1)

        status_str = "🔥 DUE FOR REVIEW" if note.is_due(self.scheduler_manager) else "✓ RETENTION SATISFIED"
        status_color = "#ef4444" if note.is_due(self.scheduler_manager) else "#10b981"

        self.lbl_note_summary.setText(
            f"Note: '{note.title}' [{note.note_type.upper()}]  |  "
            f"Joint Retrievability P(∩ A_i): <font color='{status_color}'>{joint_pct}%</font> (Target R: {target_pct}%)  |  "
            f"Status: <font color='{status_color}'>{status_str}</font>"
        )

        # Populate Per-Card Breakdown Table
        self.table_cards.setRowCount(len(note.cards))
        for row, card in enumerate(note.cards):
            r_now = self.scheduler_manager.get_card_retrievability(card, now_dt)
            r_pct = round(r_now * 100, 1)
            fc = card.fsrs_card
            stab = f"{fc.stability:.1f}d" if fc.stability is not None else "New"
            diff = f"{fc.difficulty:.1f}" if fc.difficulty is not None else "New"
            state_str = card.get_state_name()

            self.table_cards.setItem(row, 0, QTableWidgetItem(f"#{row+1} [{card.get_hex_id()}]: {card.get_title()}"))
            self.table_cards.setItem(row, 1, QTableWidgetItem(f"{r_pct}%"))
            self.table_cards.setItem(row, 2, QTableWidgetItem(stab))
            self.table_cards.setItem(row, 3, QTableWidgetItem(diff))
            self.table_cards.setItem(row, 4, QTableWidgetItem(state_str))

        # Populate Historical Review Logs Table for cards in this note
        all_logs: List[ReviewLogRecord] = course_storage.load_review_logs(self.course.name)
        card_ids = {c.item_id for c in note.cards}
        note_logs = [l for l in all_logs if l.card_id in card_ids]

        rating_names = {1: "Again", 2: "Hard", 3: "Good", 4: "Easy"}

        self.table_history.setRowCount(len(note_logs))
        for row, rlog in enumerate(reversed(note_logs)):
            r_name = rating_names.get(rlog.rating, str(rlog.rating))
            
            # Format datetime
            try:
                dt = datetime.fromisoformat(rlog.review_time)
                dt_str = dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                dt_str = str(rlog.review_time)[:19]

            sched_str = f"{rlog.scheduled_days}d" if rlog.scheduled_days else "-"

            self.table_history.setItem(row, 0, QTableWidgetItem(to_hex_id(rlog.card_id)))

            self.table_history.setItem(row, 1, QTableWidgetItem(r_name))
            self.table_history.setItem(row, 2, QTableWidgetItem(dt_str))
            self.table_history.setItem(row, 3, QTableWidgetItem(sched_str))

        # Update Chart.js Decay Curves
        if not hasattr(self, "is_page_loaded") or not self.is_page_loaded:
            return


        scale_mode = self.combo_scale.currentData() if hasattr(self, "combo_scale") and self.combo_scale else "24h"

        if scale_mode == "24h":
            time_steps = [timedelta(hours=h) for h in range(0, 25)]
            time_labels = [f"t+{h}h" if h > 0 else "Now" for h in range(0, 25)]
        elif scale_mode == "48h":
            time_steps = [timedelta(hours=h) for h in range(0, 49, 2)]
            time_labels = [f"t+{h}h" if h > 0 else "Now" for h in range(0, 49, 2)]
        elif scale_mode == "7d":
            time_steps = [timedelta(hours=h) for h in range(0, 7 * 24 + 1, 6)]
            time_labels = [f"t+{h // 24}d {h % 24}h" if h > 0 else "Now" for h in range(0, 7 * 24 + 1, 6)]
        elif scale_mode == "90d":
            time_steps = [timedelta(days=d) for d in range(0, 91, 3)]
            time_labels = [f"t+{d}d" if d > 0 else "Now" for d in range(0, 91, 3)]
        else:  # "30d"
            time_steps = [timedelta(days=d) for d in range(0, 31)]
            time_labels = [f"t+{d}d" if d > 0 else "Now" for d in range(0, 31)]

        datasets = []
        colors = ["#38bdf8", "#10b981", "#f59e0b", "#ec4899", "#8b5cf6", "#14b8a6"]

        note_total_curve = [1.0] * len(time_steps)

        for idx, card in enumerate(note.cards):
            card_curve = []
            for dt_delta in time_steps:
                target_dt = now_dt + dt_delta
                r_i = self._get_continuous_card_retrievability(card, target_dt)
                card_curve.append(round(r_i * 100, 1))


            for t_idx, val in enumerate(card_curve):
                note_total_curve[t_idx] *= (val / 100.0)

            c_color = colors[idx % len(colors)]
            datasets.append({
                "label": f"Card A_{idx+1}: {card.get_title()[:20]}",
                "data": card_curve,
                "borderColor": c_color,
                "backgroundColor": c_color,
                "borderWidth": 2,
                "fill": False,
                "tension": 0.3
            })

        note_total_percentages = [round(val * 100, 1) for val in note_total_curve]
        datasets.insert(0, {
            "label": f"★ Total Note P(∩ A_i) [{note.note_type.upper()}]",
            "data": note_total_percentages,
            "borderColor": "#6366f1",
            "backgroundColor": "rgba(99, 102, 241, 0.1)",
            "borderWidth": 4,
            "fill": True,
            "tension": 0.3
        })

        target_r_pct = round(note.desired_retention * 100, 1)
        datasets.append({
            "label": f"Target Retention Threshold (R = {target_r_pct}%)",
            "data": [target_r_pct] * len(time_steps),
            "borderColor": "#ef4444",
            "borderWidth": 2,
            "borderDash": [6, 6],
            "fill": False,
            "pointRadius": 0
        })

        chart_title = f"Retrievability Decay: '{note.title}' ({scale_mode.upper()} Scale)"

        title_json = json.dumps(chart_title)
        labels_json = json.dumps(time_labels)
        datasets_json = json.dumps(datasets)

        js = f"if (typeof renderChart === 'function') {{ renderChart({title_json}, {labels_json}, {datasets_json}); }}"
        self.browser.page().runJavaScript(js)

