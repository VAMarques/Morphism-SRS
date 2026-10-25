from __future__ import annotations

import sqlite3

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from morphism_srs.config import AppConfig
from morphism_srs.controllers.browser_controller import BrowserController
from morphism_srs.controllers.event_bus import EventBus
from morphism_srs.controllers.explorer_controller import ExplorerController
from morphism_srs.controllers.review_controller import ReviewController
from morphism_srs.storage.media_vault import MediaVault
from morphism_srs.theming.delegates import set_widget_props
from morphism_srs.theming.theme_manager import ThemeManager
from morphism_srs.ui.dialogs.mobile_qr_dialog import MobileQRDialog
from morphism_srs.ui.dialogs.scratchbook_dialog import ScratchbookDialog
from morphism_srs.ui.dialogs.settings_dialog import SettingsDialog
from morphism_srs.ui.views.browser_view import BrowserView
from morphism_srs.ui.views.courses_view import CoursesView
from morphism_srs.ui.views.explorer_view import ExplorerView
from morphism_srs.ui.views.review_view import ReviewView
from morphism_srs.ui.views.stats_view import StatsView
from morphism_srs.ui.window_sizing import apply_relative_geometry
from morphism_srs.web_engine.web_profile import WebEngineProfileManager


class MainWindow(QMainWindow):
    """Main Desktop Window shell with left navigation sidebar, QStackedWidget views, and status bar."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        config: AppConfig,
        media_vault: MediaVault,
        theme_manager: ThemeManager,
        web_profile: WebEngineProfileManager,
        version: str | None = None,
    ) -> None:
        super().__init__()
        self.app_version = version or getattr(config, "version", "0.2.2")
        self.setWindowTitle(f"Morphism SRS Prototype 2 (v{self.app_version}) — Mathematical Knowledge Graph & Spaced Repetition")

        ico_path = config.paths.icons_dir / "icon.ico"
        png_path = config.paths.icons_dir / "icon.png"
        target_icon = ico_path if ico_path.exists() else png_path
        if target_icon.exists():
            self.setWindowIcon(QIcon(str(target_icon)))

        apply_relative_geometry(
            self,
            width_ratio=float(config.get("window_width_ratio", 0.85)),
            height_ratio=float(config.get("window_height_ratio", 0.85)),
            min_width=940,
            min_height=620,
            center=True,
        )

        self.conn = conn
        self.config = config
        self.media_vault = media_vault
        self.theme_manager = theme_manager
        self.web_profile = web_profile

        self.event_bus = EventBus()
        self.review_controller = ReviewController(conn, self.event_bus)
        self.explorer_controller = ExplorerController(conn, self.event_bus)
        self.browser_controller = BrowserController(conn, self.event_bus)

        self._nav_buttons: dict[str, QPushButton] = {}
        self._tab_indices: dict[str, int] = {}

        self._build_ui()
        self.event_bus.navigate_to_tab.connect(self.switch_tab)
        self.event_bus.status_message.connect(self._on_status_message)

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Left Navigation Sidebar
        sidebar = QFrame(central)
        sidebar.setFixedWidth(210)
        set_widget_props(sidebar, role="sidebar")
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(12, 16, 12, 16)
        sb_layout.setSpacing(6)

        brand = QLabel("MORPHISM SRS", sidebar)
        set_widget_props(brand, role="title")
        sb_layout.addWidget(brand)

        sub_brand = QLabel(f"Prototype 2 • v{self.app_version}", sidebar)
        set_widget_props(sub_brand, role="muted")
        sb_layout.addWidget(sub_brand)
        sb_layout.addSpacing(12)

        nav_items = [
            ("courses", "📘  Courses & Decks"),
            ("explorer", "🕸️  Graph Explorer"),
            ("review", "⚡  Review Session"),
            ("browser", "🗂️  Card Browser"),
            ("stats", "📊  Statistics"),
        ]
        for key, label in nav_items:
            btn = QPushButton(label, sidebar)
            set_widget_props(btn, nav="true", active="false")
            btn.clicked.connect(lambda _=False, k=key: self.switch_tab(k))
            self._nav_buttons[key] = btn
            sb_layout.addWidget(btn)

        sb_layout.addStretch(1)

        scratch_btn = QPushButton("✏️  Scratchbook", sidebar)
        set_widget_props(scratch_btn, nav="true", active="false")
        scratch_btn.clicked.connect(self._on_open_scratchbook)
        sb_layout.addWidget(scratch_btn)

        mobile_btn = QPushButton("📱  Mobile QR Sync", sidebar)
        set_widget_props(mobile_btn, nav="true", active="false")
        mobile_btn.clicked.connect(self._on_open_mobile_qr)
        sb_layout.addWidget(mobile_btn)

        settings_btn = QPushButton("⚙️  Settings & Theme", sidebar)
        set_widget_props(settings_btn, nav="true", active="false")
        settings_btn.clicked.connect(self._on_open_settings)
        sb_layout.addWidget(settings_btn)

        main_layout.addWidget(sidebar)

        # Central Stacked Views
        self.stack = QStackedWidget(central)
        self.stack.setMinimumWidth(680)
        self.courses_view = CoursesView(self.conn, self.media_vault, self.review_controller, self.event_bus, self.stack)
        self.explorer_view = ExplorerView(
            self.conn,
            self.config,
            self.media_vault,
            self.web_profile,
            self.theme_manager,
            self.explorer_controller,
            self.review_controller,
            self.event_bus,
            self.stack,
        )
        self.review_view = ReviewView(
            self.conn,
            self.config,
            self.media_vault,
            self.web_profile,
            self.review_controller,
            self.event_bus,
            self.stack,
        )
        self.browser_view = BrowserView(
            self.conn,
            self.config,
            self.media_vault,
            self.web_profile,
            self.browser_controller,
            self.review_controller,
            self.event_bus,
            self.stack,
        )
        self.stats_view = StatsView(self.conn, self.web_profile, self.event_bus, self.stack)

        for key, widget in [
            ("courses", self.courses_view),
            ("explorer", self.explorer_view),
            ("review", self.review_view),
            ("browser", self.browser_view),
            ("stats", self.stats_view),
        ]:
            idx = self.stack.addWidget(widget)
            self._tab_indices[key] = idx

        main_layout.addWidget(self.stack, 1)

        status_bar = QStatusBar(self)
        self.setStatusBar(status_bar)
        status_bar.showMessage(f"Morphism SRS Prototype 2 (v{self.app_version}) Ready — Offline MathJax 3 + SQLite WAL + FSRS v5", 5000)

        self.switch_tab("courses")

    def switch_tab(self, tab_key: str) -> None:
        if tab_key not in self._tab_indices:
            return
        self.stack.setCurrentIndex(self._tab_indices[tab_key])
        for k, btn in self._nav_buttons.items():
            set_widget_props(btn, nav="true", active="true" if k == tab_key else "false")

        if tab_key == "review":
            self.review_view.setFocus()
        elif tab_key == "browser":
            self.browser_view.refresh_all()
        elif tab_key == "stats":
            self.stats_view.refresh_stats()

    def _on_status_message(self, msg: str, timeout_ms: int) -> None:
        if self.statusBar():
            self.statusBar().showMessage(msg, timeout_ms)

    def _on_open_scratchbook(self) -> None:
        dlg = ScratchbookDialog(self.conn, self.web_profile, self.event_bus, config=self.config, parent=self)
        dlg.exec()

    def _on_open_mobile_qr(self) -> None:
        dlg = MobileQRDialog(
            conn=self.conn,
            review_controller=self.review_controller,
            media_vault=self.media_vault,
            web_root=self.config.paths.web_dir,
            event_bus=self.event_bus,
            parent=self,
        )
        dlg.exec()

    def _on_open_settings(self) -> None:
        dlg = SettingsDialog(self.conn, self.config, self.theme_manager, parent=self)
        dlg.exec()

    def closeEvent(self, event) -> None:
        self.web_profile.cleanup_all_views()
        super().closeEvent(event)
