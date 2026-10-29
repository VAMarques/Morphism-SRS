"""Cross-platform AppData directory and application configuration management."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
from typing import Any

try:
    import platformdirs
except ImportError:
    platformdirs = None  # type: ignore[assignment]


APP_NAME = "MorphismSRS"


def get_project_root() -> Path:
    """Return the root directory of the repository or bundle."""
    return Path(__file__).resolve().parent.parent.parent


def get_resources_dir() -> Path:
    """Return the path to bundled static resources (`src/morphism_srs/resources`)."""
    return Path(__file__).resolve().parent / "resources"


class AppPaths:
    """Manages OS-native user data directories (Windows %APPDATA%, Linux XDG, macOS Application Support)
    as well as Portable Mode when `portable.flag` is present.
    """

    def __init__(self, custom_base_dir: Path | str | None = None) -> None:
        if custom_base_dir is not None:
            self.base_dir = Path(custom_base_dir).resolve()
        else:
            root = get_project_root()
            env_override = os.environ.get("MORPHISM_USER_DATA_DIR")
            if env_override:
                self.base_dir = Path(env_override).resolve()
            elif (root / "portable.flag").exists():
                self.base_dir = (root / "user_data").resolve()
            elif platformdirs is not None:
                self.base_dir = Path(
                    platformdirs.user_data_dir(APP_NAME, appauthor=False, roaming=True)
                ).resolve()
            else:
                self.base_dir = (Path.home() / f".{APP_NAME.lower()}").resolve()

        # Unify user data: ensure no redundant 'Morphism' folder exists alongside 'MorphismSRS'
        if custom_base_dir is None:
            legacy_dir = self.base_dir.parent / "Morphism"
            if legacy_dir.exists() and legacy_dir.is_dir() and legacy_dir != self.base_dir:
                try:
                    shutil.rmtree(legacy_dir, ignore_errors=True)
                except Exception:
                    pass

        res_dir = get_resources_dir()
        self.resources_dir = res_dir
        self.defaults_dir = res_dir / "defaults"
        self.themes_dir = res_dir / "themes"
        self.styles_dir = res_dir / "styles"
        self.web_dir = res_dir / "web"
        self.icons_dir = res_dir / "icons"
        self.schema_sql_path = Path(__file__).resolve().parent / "storage" / "schema_v2.sql"

        self.db_path = self.base_dir / "morphism_v2.sqlite3"
        self.media_dir = self.base_dir / "media"
        self.config_dir = self.base_dir / "config"
        self.user_themes_dir = self.base_dir / "themes"
        self.backups_dir = self.base_dir / "backups"
        self.logs_dir = self.base_dir / "logs"

        self.settings_file = self.config_dir / "settings.json"
        self.macros_file = self.config_dir / "mathjax_macros.json"
        self.editor_buttons_file = self.config_dir / "editor_buttons.json"

    @classmethod
    def resolve(cls, custom_base_dir: Path | str | None = None) -> AppPaths:
        instance = cls(custom_base_dir=custom_base_dir)
        instance.ensure_dirs()
        return instance

    def ensure_dirs(self) -> None:
        """Create all required user data subdirectories if they do not exist."""
        for directory in (
            self.base_dir,
            self.media_dir,
            self.config_dir,
            self.user_themes_dir,
            self.backups_dir,
            self.logs_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


DEFAULT_SETTINGS: dict[str, Any] = {
    "theme": "dark_slate",
    "active_course_id": None,
    "window_width_ratio": 0.85,
    "window_height_ratio": 0.85,
    "default_desired_retention": 0.80,
    "enable_auto_backups": True,
    "max_backups": 10,
}


class AppConfig:
    """JSON configuration store for user preferences, MathJax macros, and toolbar buttons."""

    def __init__(self, paths: AppPaths | None = None) -> None:
        self.paths = paths or AppPaths.resolve()
        self.paths.ensure_dirs()
        self._settings: dict[str, Any] = dict(DEFAULT_SETTINGS)
        self.load()

    def load(self) -> None:
        if self.paths.settings_file.exists():
            try:
                data = json.loads(self.paths.settings_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._settings.update(data)
            except Exception:
                pass
        else:
            self.save()

    def save(self) -> None:
        self.paths.ensure_dirs()
        self.paths.settings_file.write_text(
            json.dumps(self._settings, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def get(self, key: str, default: Any = None) -> Any:
        return self._settings.get(key, DEFAULT_SETTINGS.get(key, default))

    def set(self, key: str, value: Any, auto_save: bool = True) -> None:
        self._settings[key] = value
        if auto_save:
            self.save()

    @property
    def version(self) -> str:
        """Application version string as configured or package default."""
        from morphism_srs import __version__
        return str(self.get("version", __version__))

    def _load_default_mathjax_config(self) -> dict[str, Any]:
        default_file = self.paths.defaults_dir / "mathjax_macros.json"
        if default_file.exists():
            try:
                data = json.loads(default_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        return {
            "inlineMath": [["$", "$"], ["\\(", "\\)"]],
            "displayMath": [["$$", "$$"], ["\\[", "\\]"]],
            "processEscapes": True,
            "packages": {"[+]": ["color", "ams"]},
            "macros": {},
        }

    def load_mathjax_macros(self) -> dict[str, Any]:
        default_cfg = self._load_default_mathjax_config()
        default_macros = dict(default_cfg.get("macros", {}))
        if not self.paths.macros_file.exists():
            self.save_mathjax_macros(default_macros)
            return default_macros
        try:
            data = json.loads(self.paths.macros_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                user_macros = (
                    data.get("macros", data)
                    if "macros" in data and isinstance(data["macros"], dict)
                    else data
                )
                merged = dict(default_macros)
                if isinstance(user_macros, dict):
                    merged.update(user_macros)
                return merged
        except Exception:
            pass
        return default_macros

    def load_mathjax_tex_config(self) -> dict[str, Any]:
        """Return the complete MathJax `tex` configuration object including packages and macros."""
        cfg = self._load_default_mathjax_config()
        cfg["macros"] = self.load_mathjax_macros()
        cfg.pop("autoload", None)
        return cfg

    def save_mathjax_macros(self, macros: dict[str, Any]) -> None:
        cfg = self._load_default_mathjax_config()
        cfg["macros"] = macros
        cfg.pop("autoload", None)
        try:
            self.paths.macros_file.parent.mkdir(parents=True, exist_ok=True)
            self.paths.macros_file.write_text(
                json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            pass

    def load_editor_buttons(self) -> list[dict[str, Any]]:
        if not self.paths.editor_buttons_file.exists():
            default_file = self.paths.defaults_dir / "editor_buttons.json"
            if default_file.exists():
                self.paths.editor_buttons_file.write_text(
                    default_file.read_text(encoding="utf-8"), encoding="utf-8"
                )
        if self.paths.editor_buttons_file.exists():
            try:
                data = json.loads(self.paths.editor_buttons_file.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return data
            except Exception:
                pass
        return []
