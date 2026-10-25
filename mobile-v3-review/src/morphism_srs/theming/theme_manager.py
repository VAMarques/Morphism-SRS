from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication


class ThemeManager(QObject):
    """Single source of truth for Design Tokens, compiling app.qss.tmpl and WebEngine CSS variables."""

    theme_changed = Signal(str)
    PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")

    def __init__(self, themes_dir: Path, styles_dir: Path, initial_theme: str = "dark_slate") -> None:
        super().__init__()
        self.themes_dir = themes_dir
        self.styles_dir = styles_dir
        self._themes: dict[str, dict[str, Any]] = {}
        self._current_theme_id: str = initial_theme
        self.reload_themes()

    def reload_themes(self) -> None:
        self._themes.clear()
        if not self.themes_dir.exists():
            return
        for p in sorted(self.themes_dir.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                tid = str(data.get("id") or p.stem)
                self._themes[tid] = data
            except Exception:
                continue
        if self._current_theme_id not in self._themes and self._themes:
            self._current_theme_id = next(iter(self._themes.keys()))

    def available_themes(self) -> list[tuple[str, str]]:
        """Returns [(theme_id, display_name), ...]."""
        return [(tid, str(data.get("name", tid))) for tid, data in self._themes.items()]

    @property
    def current_theme_id(self) -> str:
        return self._current_theme_id

    @property
    def tokens(self) -> dict[str, str]:
        data = self._themes.get(self._current_theme_id, {})
        return dict(data.get("tokens", {}))

    def token(self, key: str, default: str = "#89b4fa") -> str:
        return self.tokens.get(key, default)

    def qcolor(self, key: str, default: str = "#89b4fa") -> QColor:
        return QColor(self.token(key, default))

    def compile_qss(self) -> str:
        tmpl_path = self.styles_dir / "app.qss.tmpl"
        if not tmpl_path.exists():
            return ""
        raw_tmpl = tmpl_path.read_text(encoding="utf-8")
        tok_map = self.tokens
        return self.PLACEHOLDER_RE.sub(lambda m: tok_map.get(m.group(1), m.group(0)), raw_tmpl)

    def compile_css_variables_js(self) -> str:
        """Returns a JS snippet that updates document.documentElement CSS variables."""
        assignments: list[str] = []
        for k, v in self.tokens.items():
            css_var = "--" + k.replace("_", "-")
            safe_val = v.replace('"', '\\"')
            assignments.append(f'document.documentElement.style.setProperty("{css_var}", "{safe_val}");')
        return "\n".join(assignments)

    def apply_theme(self, theme_id: str | None = None, app: QApplication | None = None) -> None:
        if theme_id and theme_id in self._themes:
            self._current_theme_id = theme_id
        qss = self.compile_qss()
        target_app = app or QApplication.instance()
        if isinstance(target_app, QApplication):
            target_app.setStyleSheet(qss)
        self.theme_changed.emit(self._current_theme_id)
