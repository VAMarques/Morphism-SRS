import os
import json
from datetime import datetime, timezone, timedelta, date
from typing import List, Dict
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                               QGroupBox, QSplitter, QScrollArea)

from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtCore import Qt, QUrl
from models import Course, ReviewLogRecord
from scheduler_manager import SchedulerManager
import course_storage

ASSETS_DIR = os.path.abspath("assets").replace("\\", "/")

CHART_JS_PATH = os.path.join(os.path.abspath("assets"), "chart.js")
CHART_JS_CODE = ""
if os.path.exists(CHART_JS_PATH):
    with open(CHART_JS_PATH, "r", encoding="utf-8") as f:
        CHART_JS_CODE = f.read()

HEATMAP_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {
            background-color: #0f172a;
            color: #f8fafc;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            margin: 0;
            padding: 8px;
        }
        .container {
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 10px;
            padding: 14px;
        }
        .header-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }
        .header-title {
            font-weight: bold;
            font-size: 15px;
            color: #38bdf8;
        }
        select {
            background: #0f172a;
            color: #f8fafc;
            border: 1px solid #475569;
            padding: 4px 10px;
            border-radius: 6px;
            font-size: 13px;
            font-weight: bold;
            cursor: pointer;
        }
        .heatmap-grid {
            display: grid;
            grid-template-rows: repeat(7, 13px);
            grid-auto-flow: column;
            gap: 3px;
            overflow-x: auto;
            padding-bottom: 6px;
        }
        .day-cell {
            width: 13px;
            height: 13px;
            border-radius: 2px;
            box-sizing: border-box;
            transition: transform 0.1s ease;
        }
        .day-cell:hover {
            transform: scale(1.3);
            z-index: 10;
            outline: 1px solid #ffffff;
        }
        /* Red gradient scale: redder with more reviews! */
        .cell-level-0 { background-color: #334155; opacity: 0.3; } /* Past day with 0 reviews */
        .cell-level-1 { background-color: #7f1d1d; } /* 1-2 reviews: dark red */
        .cell-level-2 { background-color: #b91c1c; } /* 3-5 reviews: medium red */
        .cell-level-3 { background-color: #ef4444; } /* 6-10 reviews: bright red */
        .cell-level-4 { background-color: #f87171; box-shadow: 0 0 6px rgba(248, 113, 113, 0.8); } /* 11+ reviews: vibrant red */
        .future-cell {
            visibility: hidden; /* Only render squares for days that have actually passed! */
        }
        .legend-bar {
            display: flex;
            align-items: center;
            justify-content: flex-end;
            gap: 6px;
            font-size: 12px;
            color: #94a3b8;
            margin-top: 10px;
        }
        .legend-box {
            width: 12px;
            height: 12px;
            border-radius: 2px;
        }
    </style>
    <script>
        let allYearData = {};
        let currentYear = new Date().getFullYear();

        window.renderHeatmap = function(yearDataJson, availableYears) {
            allYearData = yearDataJson;
            let selectEl = document.getElementById('year-select');
            if (selectEl) {
                selectEl.innerHTML = '';
                availableYears.forEach(y => {
                    let opt = document.createElement('option');
                    opt.value = y;
                    opt.innerText = "Year " + y;
                    if (y === currentYear) opt.selected = true;
                    selectEl.appendChild(opt);
                });
                if (!availableYears.includes(currentYear) && availableYears.length > 0) {
                    currentYear = availableYears[0];
                }
            }
            displayHeatmapForYear(currentYear);
        };

        function switchYear(y) {
            currentYear = parseInt(y);
            displayHeatmapForYear(currentYear);
        }

        function displayHeatmapForYear(year) {
            let container = document.getElementById('heatmap-container');
            if (!container) return;
            container.innerHTML = '';

            let today = new Date();

            let startDate = new Date(year, 0, 1);
            let endDate = new Date(year, 11, 31);
            let cur = new Date(startDate);
            
            while (cur <= endDate) {
                let yearStr = cur.getFullYear();
                let monthStr = String(cur.getMonth() + 1).padStart(2, '0');
                let dayStr = String(cur.getDate()).padStart(2, '0');
                let dateStr = yearStr + "-" + monthStr + "-" + dayStr;

                let count = (allYearData[dateStr] || 0);

                let cell = document.createElement('div');
                cell.className = 'day-cell';

                // Check if date is in the future
                if (cur > today) {
                    cell.classList.add('future-cell');
                } else {
                    if (count === 0) {
                        cell.classList.add('cell-level-0');
                        cell.title = dateStr + ": 0 reviews";
                    } else if (count <= 2) {
                        cell.classList.add('cell-level-1');
                        cell.title = dateStr + ": " + count + " review" + (count > 1 ? "s" : "");
                    } else if (count <= 5) {
                        cell.classList.add('cell-level-2');
                        cell.title = dateStr + ": " + count + " reviews";
                    } else if (count <= 10) {
                        cell.classList.add('cell-level-3');
                        cell.title = dateStr + ": " + count + " reviews";
                    } else {
                        cell.classList.add('cell-level-4');
                        cell.title = dateStr + ": " + count + " reviews (🔥 High Activity!)";
                    }
                }

                container.appendChild(cell);
                cur.setDate(cur.getDate() + 1);
            }
        }
    </script>
</head>
<body>
    <div class="container">
        <div class="header-bar">
            <div class="header-title">📅 Yearly Review Contribution Grid</div>
            <div>
                <select id="year-select" onchange="switchYear(this.value)"></select>
            </div>
        </div>
        <div id="heatmap-container" class="heatmap-grid"></div>
        <div class="legend-bar">
            <span>Less</span>
            <div class="legend-box cell-level-0"></div>
            <div class="legend-box cell-level-1"></div>
            <div class="legend-box cell-level-2"></div>
            <div class="legend-box cell-level-3"></div>
            <div class="legend-box cell-level-4"></div>
            <span>More (Redder)</span>
        </div>
    </div>
</body>
</html>
"""

BARPLOT_HTML_TEMPLATE = f"""<!DOCTYPE html>
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
            border-radius: 12px;
            padding: 16px;
        }}
        h3 {{ color: #38bdf8; margin-top: 0; font-size: 16px; }}
        .canvas-holder {{ height: 240px; position: relative; }}
    </style>
    <script>
        let barChart = null;

        window.renderBarPlot = function(labels, counts, bgColors) {{
            let canvas = document.getElementById('dueBarChart');
            if (!canvas || typeof Chart === 'undefined') return;
            let ctx = canvas.getContext('2d');
            if (barChart) barChart.destroy();

            barChart = new Chart(ctx, {{
                type: 'bar',
                data: {{
                    labels: labels,
                    datasets: [{{
                        label: 'Due Cards',
                        data: counts,
                        backgroundColor: bgColors,
                        borderWidth: 0,
                        borderRadius: 4
                    }}]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {{
                        x: {{
                            grid: {{ color: '#334155' }},
                            ticks: {{ color: '#94a3b8', font: {{ size: 11 }} }}
                        }},
                        y: {{
                            beginAtZero: true,
                            grid: {{ color: '#334155' }},
                            ticks: {{ color: '#94a3b8', stepSize: 1 }}
                        }}
                    }},
                    plugins: {{
                        legend: {{ display: false }}
                    }}
                }}
            }});
        }};
    </script>
</head>
<body>
    <div class="container">
        <h3>📊 Due Cards Histogram (Next 30 Days & Overdue)</h3>
        <div class="canvas-holder">
            <canvas id="dueBarChart"></canvas>
        </div>
    </div>
</body>
</html>
"""

class StatsWidget(QWidget):
    """Stats tab with Anki-style yearly review heatmap grid and due cards histogram barplot."""

    def __init__(self, scheduler_manager: SchedulerManager, parent=None):
        super().__init__(parent)
        self.scheduler_manager = scheduler_manager
        self.current_course: Course = None
        self.is_barplot_loaded = False
        self.is_heatmap_loaded = False

        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)

        # Header Title
        header_layout = QHBoxLayout()
        self.lbl_title = QLabel("📈 Learning Statistics & Review History")
        self.lbl_title.setStyleSheet("font-size: 20px; font-weight: bold; color: #38bdf8;")
        header_layout.addWidget(self.lbl_title)
        header_layout.addStretch()

        self.lbl_stats_summary = QLabel("Total Reviews: 0  |  Active Days: 0")
        self.lbl_stats_summary.setStyleSheet("background-color: #1e293b; border: 1px solid #334155; padding: 6px 14px; border-radius: 6px; font-weight: bold; color: #10b981;")
        header_layout.addWidget(self.lbl_stats_summary)

        main_layout.addLayout(header_layout)

        # Scroll Area for Constant-Sized Stats Charts
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(16)

        # 1. Top Section: Yearly Review Heatmap WebEngine View
        heatmap_group = QGroupBox("📅 Yearly Review Heatmap")
        heatmap_layout = QVBoxLayout(heatmap_group)

        self.heatmap_browser = QWebEngineView()
        self.heatmap_browser.setMinimumHeight(260)
        self.heatmap_browser.setHtml(HEATMAP_HTML_TEMPLATE, QUrl.fromLocalFile(ASSETS_DIR + "/"))
        self.heatmap_browser.loadFinished.connect(self._on_heatmap_loaded)
        heatmap_layout.addWidget(self.heatmap_browser)
        scroll_layout.addWidget(heatmap_group)

        # 2. Bottom Section: Due Cards Histogram Barplot (Chart.js)
        barplot_group = QGroupBox("📊 Due Cards Barplot Forecast")
        barplot_layout = QVBoxLayout(barplot_group)

        self.barplot_browser = QWebEngineView()
        self.barplot_browser.setMinimumHeight(320)
        self.barplot_browser.setHtml(BARPLOT_HTML_TEMPLATE, QUrl.fromLocalFile(ASSETS_DIR + "/"))
        self.barplot_browser.loadFinished.connect(self._on_barplot_loaded)
        barplot_layout.addWidget(self.barplot_browser)
        scroll_layout.addWidget(barplot_group)

        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area, stretch=1)


    def _on_heatmap_loaded(self, ok: bool):
        self.is_heatmap_loaded = True
        self.refresh_heatmap()

    def _on_barplot_loaded(self, ok: bool):
        self.is_barplot_loaded = True
        self.refresh_due_barplot()

    def load_course_stats(self, course: Course):
        self.current_course = course
        self.lbl_title.setText(f"📈 Statistics for Course: '{course.name}'")

        self.refresh_heatmap()
        self.refresh_due_barplot()

    def refresh_heatmap(self):
        """Render yearly review contribution grid with year selector and red gradient."""
        if not hasattr(self, "is_heatmap_loaded") or not self.is_heatmap_loaded or not self.current_course:
            return

        logs: List[ReviewLogRecord] = course_storage.load_review_logs(self.current_course.name)

        counts_by_date: Dict[str, int] = {}
        years_set = {date.today().year}

        for rlog in logs:
            try:
                dt = datetime.fromisoformat(rlog.review_time)
                d_str = dt.astimezone().strftime("%Y-%m-%d")
                counts_by_date[d_str] = counts_by_date.get(d_str, 0) + 1
                years_set.add(dt.year)
            except Exception:
                d_str = str(rlog.review_time)[:10]
                counts_by_date[d_str] = counts_by_date.get(d_str, 0) + 1
                try:
                    years_set.add(int(d_str[:4]))
                except Exception:
                    pass

        total_reviews = len(logs)
        active_days = len(counts_by_date)
        self.lbl_stats_summary.setText(f"Total Reviews: {total_reviews}  |  Active Days: {active_days}")

        available_years = sorted(list(years_set), reverse=True)

        counts_json = json.dumps(counts_by_date)
        years_json = json.dumps(available_years)

        js = f"if (typeof renderHeatmap === 'function') {{ renderHeatmap({counts_json}, {years_json}); }}"
        self.heatmap_browser.page().runJavaScript(js)

    def refresh_due_barplot(self):
        """Render due cards histogram by day offset (-7 overdue to +30 days)."""
        if not hasattr(self, "is_barplot_loaded") or not self.is_barplot_loaded or not self.current_course:
            return

        now_dt = datetime.now(timezone.utc)
        today_date = now_dt.date()

        day_offsets = list(range(-7, 31))  # -7 days to +30 days
        counts = [0] * len(day_offsets)
        bg_colors = []

        for offset in day_offsets:
            if offset < 0:
                bg_colors.append("#ef4444")
            elif offset == 0:
                bg_colors.append("#f59e0b")
            else:
                bg_colors.append("#38bdf8")

        for offset_idx, offset in enumerate(day_offsets):
            target_dt = now_dt + timedelta(days=offset)
            target_py_date = target_dt.date()

            due_cnt = 0
            for note in self.current_course.notes:
                for card in note.cards:
                    if card.fsrs_card.due and card.fsrs_card.last_review:
                        card_due_date = card.fsrs_card.due.date()
                        if offset < 0 and card_due_date < today_date and offset == -1:
                            due_cnt += 1
                        elif card_due_date == target_py_date:
                            due_cnt += 1
                    elif card.fsrs_card.last_review is None and offset == 0:
                        due_cnt += 1

            counts[offset_idx] = due_cnt

        labels = [f"{-offset}d Overdue" if offset < 0 else ("Today" if offset == 0 else f"+{offset}d") for offset in day_offsets]

        labels_json = json.dumps(labels)
        counts_json = json.dumps(counts)
        colors_json = json.dumps(bg_colors)

        js = f"if (typeof renderBarPlot === 'function') {{ renderBarPlot({labels_json}, {counts_json}, {colors_json}); }}"
        self.barplot_browser.page().runJavaScript(js)
