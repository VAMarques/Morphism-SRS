from datetime import datetime, timezone, timedelta, date
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                               QPushButton, QTableWidget, QTableWidgetItem, 
                               QHeaderView, QCalendarWidget, QGroupBox, QSplitter)
from PySide6.QtCore import Qt, QDate
from models import Course
from scheduler_manager import SchedulerManager

class DueForecastDialog(QDialog):
    """Dialog for viewing due notes and cards forecasted across future dates."""

    def __init__(self, course: Course, scheduler_manager: SchedulerManager, parent=None):
        super().__init__(parent)
        self.course = course
        self.scheduler_manager = scheduler_manager
        self.selected_target_dt = datetime.now(timezone.utc)

        self.setWindowTitle(f"📅 Due Forecast - Course: {course.name}")
        self.resize(900, 600)
        self._setup_ui()
        self._update_forecast_for_date(QDate.currentDate())

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)

        # Header Title
        lbl_header = QLabel(f"Forecast Due Notes & Cards for '{self.course.name}'")
        lbl_header.setStyleSheet("font-size: 18px; font-weight: bold; color: #38bdf8;")
        main_layout.addWidget(lbl_header)

        splitter = QSplitter(Qt.Horizontal)

        # Left Column: Calendar Selection
        cal_group = QGroupBox("Select Target Review Date")
        cal_layout = QVBoxLayout(cal_group)
        self.calendar = QCalendarWidget()
        self.calendar.setGridVisible(True)
        self.calendar.setSelectedDate(QDate.currentDate())
        self.calendar.setMinimumDate(QDate.currentDate())
        self.calendar.selectionChanged.connect(self._on_date_changed)
        cal_layout.addWidget(self.calendar)
        splitter.addWidget(cal_group)

        # Right Column: Forecasted Table
        table_group = QGroupBox("Forecasted Due Notes & Joint Retention")
        table_layout = QVBoxLayout(table_group)

        self.lbl_selected_info = QLabel("Selected Date: Today")
        self.lbl_selected_info.setStyleSheet("font-size: 15px; font-weight: bold; color: #818cf8;")
        table_layout.addWidget(self.lbl_selected_info)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Note Title", "Type", "Cards", "Projected P(∩ A_i)", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        table_layout.addWidget(self.table)

        splitter.addWidget(table_group)
        splitter.setSizes([320, 580])
        main_layout.addWidget(splitter)

        # Bottom Buttons
        bottom_layout = QHBoxLayout()
        bottom_layout.addStretch()

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        bottom_layout.addWidget(btn_close)

        main_layout.addLayout(bottom_layout)

    def _on_date_changed(self):
        qdate = self.calendar.selectedDate()
        self._update_forecast_for_date(qdate)

    def _update_forecast_for_date(self, qdate: QDate):
        target_py_date = date(qdate.year(), qdate.month(), qdate.day())
        now_dt = datetime.now(timezone.utc)
        today_py_date = now_dt.date()

        days_ahead = (target_py_date - today_py_date).days
        target_dt = now_dt + timedelta(days=days_ahead)
        self.selected_target_dt = target_dt

        date_str = qdate.toString("yyyy-MM-dd (ddd)")
        self.lbl_selected_info.setText(f"Forecast for: {date_str}  (+$ {days_ahead} days)")

        self.table.setRowCount(0)

        row_idx = 0
        for note in self.course.notes:
            joint_r = note.get_joint_retention(self.scheduler_manager) if not days_ahead else self._sim_joint_retention(note, target_dt)
            ret_pct = int(joint_r * 100)

            is_due = (joint_r <= note.desired_retention) or any(c.fsrs_card.last_review is None for c in note.cards)
            status_str = "🔥 DUE" if is_due else "✓ OK"

            self.table.insertRow(row_idx)
            self.table.setItem(row_idx, 0, QTableWidgetItem(note.title))
            self.table.setItem(row_idx, 1, QTableWidgetItem("Serial Sequence" if note.is_serial_sequence() else "Standard"))
            self.table.setItem(row_idx, 2, QTableWidgetItem(str(len(note.cards))))
            self.table.setItem(row_idx, 3, QTableWidgetItem(f"{ret_pct}%"))
            
            status_item = QTableWidgetItem(status_str)
            status_item.setForeground(Qt.red if is_due else Qt.green)
            self.table.setItem(row_idx, 4, status_item)

            row_idx += 1

    def _sim_joint_retention(self, note, target_dt: datetime) -> float:
        if not note.cards:
            return 1.0
        prod = 1.0
        for c in note.cards:
            r = self.scheduler_manager.get_card_retrievability(c, target_dt)
            prod *= r
        return prod
