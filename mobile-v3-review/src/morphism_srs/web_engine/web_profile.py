from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView

from morphism_srs.config import AppConfig
from morphism_srs.storage.media_vault import MediaVault
from morphism_srs.theming.theme_manager import ThemeManager
from morphism_srs.web_engine.scheme_handler import SCHEME_NAME, MorphismSchemeHandler


class WebEngineProfileManager(QObject):
    """Configures a shared offline QWebEngineProfile with MorphismSchemeHandler, theme sync,
    and deterministic QWebEnginePage teardown to avoid profile release warnings.
    """

    def __init__(
        self,
        web_root: Path,
        media_vault: MediaVault,
        theme_manager: ThemeManager,
        config: AppConfig | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.web_root = web_root
        self.media_vault = media_vault
        self.theme_manager = theme_manager
        self.config = config or AppConfig()

        # Use an off-the-record (in-memory) profile parented to this manager
        self.profile = QWebEngineProfile(self)
        self.handler = MorphismSchemeHandler(
            web_root=web_root,
            media_vault=media_vault,
            config=self.config,
            parent=self,
        )
        self.profile.installUrlSchemeHandler(SCHEME_NAME, self.handler)

        settings = self.profile.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)

        self._tracked_views: list[QWebEngineView] = []
        self._tracked_pages: list[QWebEnginePage] = []
        self.theme_manager.theme_changed.connect(self._on_theme_changed)

        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.cleanup_all_views)

    def create_web_view(self, parent_widget=None) -> QWebEngineView:
        view = QWebEngineView(parent_widget)
        page = QWebEnginePage(self.profile, view)
        page.setBackgroundColor(self.theme_manager.qcolor("bg_primary"))
        view.setPage(page)
        view.loadFinished.connect(lambda ok, v=view: self._inject_theme_into_view(v) if ok else None)
        self._tracked_views.append(view)
        self._tracked_pages.append(page)
        view.destroyed.connect(lambda *_: self._prune_destroyed_views())
        return view

    def dispose_web_view(self, view: QWebEngineView | None) -> None:
        """Detach and delete the custom QWebEnginePage of a view before the dialog/window closes."""
        if view is None:
            return
        try:
            page = view.page()
            if page is not None and page in self._tracked_pages:
                self._tracked_pages.remove(page)
                # Replace with a temporary default-profile page before deleting custom page
                view.setPage(None)  # type: ignore[arg-type]
                page.deleteLater()
        except RuntimeError:
            pass
        if view in self._tracked_views:
            self._tracked_views.remove(view)

    def cleanup_all_views(self) -> None:
        """Destroy all custom QWebEnginePages before QWebEngineProfile is released."""
        for view in list(self._tracked_views):
            self.dispose_web_view(view)
        for page in list(self._tracked_pages):
            try:
                page.deleteLater()
            except RuntimeError:
                pass
        self._tracked_pages.clear()
        self._tracked_views.clear()

    def _prune_destroyed_views(self) -> None:
        alive: list[QWebEngineView] = []
        for v in self._tracked_views:
            try:
                _ = v.page()
                alive.append(v)
            except RuntimeError:
                continue
        self._tracked_views = alive

    def _inject_theme_into_view(self, view: QWebEngineView) -> None:
        try:
            view.page().setBackgroundColor(self.theme_manager.qcolor("bg_primary"))
            js = self.theme_manager.compile_css_variables_js()
            view.page().runJavaScript(js)
        except RuntimeError:
            pass

    def _on_theme_changed(self, _theme_id: str) -> None:
        self._prune_destroyed_views()
        for v in self._tracked_views:
            self._inject_theme_into_view(v)
