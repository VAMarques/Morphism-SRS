from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from morphism_srs.config import AppConfig, AppPaths
from morphism_srs.storage.database import DatabaseManager
from morphism_srs.storage.media_vault import MediaVault
from morphism_srs.theming.theme_manager import ThemeManager
from morphism_srs.ui.main_window import MainWindow
from morphism_srs.web_engine.scheme_handler import register_morphism_scheme
from morphism_srs.web_engine.web_profile import WebEngineProfileManager


def main(argv: list[str] | None = None) -> int:
    """Bootstrap sequence for Morphism SRS Prototype 2."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("morphism.srs.proto2")
        except Exception:
            pass

    # 1. Register morphism:// scheme before QApplication is created
    register_morphism_scheme()

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("MorphismSRS")
    app.setOrganizationName("")

    # 2. Initialize AppPaths & AppConfig
    paths = AppPaths.resolve()
    config = AppConfig(paths)

    ico_path = paths.icons_dir / "icon.ico"
    png_path = paths.icons_dir / "icon.png"
    icon_to_use = ico_path if ico_path.exists() else png_path
    if icon_to_use.exists():
        from PySide6.QtGui import QIcon
        app.setWindowIcon(QIcon(str(icon_to_use)))

    # 3. Initialize SQLite v2 Database, schema_v2.sql, and 2,000 standard tags
    db_manager = DatabaseManager(
        db_path=paths.db_path,
        schema_path=paths.schema_sql_path,
        tags_csv_path=paths.defaults_dir / "tags_default.csv",
    )
    db_manager.initialize()
    db_manager.create_backup(paths.backups_dir, max_backups=int(config.get("max_backups", 10)))

    media_vault = MediaVault(db_manager.connection, paths.media_dir)

    # 4. Initialize ThemeManager and compile QSS
    theme_manager = ThemeManager(
        themes_dir=paths.themes_dir,
        styles_dir=paths.styles_dir,
        initial_theme=str(config.get("theme", "dark_slate")),
    )
    theme_manager.apply_theme(app=app)

    # 5. Initialize shared offline WebEngine profile
    web_profile = WebEngineProfileManager(
        web_root=paths.web_dir,
        media_vault=media_vault,
        theme_manager=theme_manager,
        config=config,
        parent=app,
    )

    # 6. Show MainWindow
    window = MainWindow(
        conn=db_manager.connection,
        config=config,
        media_vault=media_vault,
        theme_manager=theme_manager,
        web_profile=web_profile,
        version=config.version,
    )
    window.show()

    exit_code = app.exec()
    web_profile.cleanup_all_views()
    del window
    db_manager.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
