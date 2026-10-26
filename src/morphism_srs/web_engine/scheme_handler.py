from __future__ import annotations

import json
import mimetypes
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject
from PySide6.QtWebEngineCore import (
    QWebEngineUrlRequestJob,
    QWebEngineUrlScheme,
    QWebEngineUrlSchemeHandler,
)

from morphism_srs.config import AppConfig
from morphism_srs.storage.media_vault import MediaVault

SCHEME_NAME = b"morphism"
_SCHEME_REGISTERED = False


def register_morphism_scheme() -> None:
    """Registers the custom morphism:// URL scheme before QApplication instantiation."""
    global _SCHEME_REGISTERED
    if _SCHEME_REGISTERED:
        return
    scheme = QWebEngineUrlScheme(SCHEME_NAME)
    scheme.setSyntax(QWebEngineUrlScheme.Syntax.Host)
    scheme.setFlags(
        QWebEngineUrlScheme.Flag.SecureScheme
        | QWebEngineUrlScheme.Flag.LocalScheme
        | QWebEngineUrlScheme.Flag.LocalAccessAllowed
        | QWebEngineUrlScheme.Flag.CorsEnabled
        | QWebEngineUrlScheme.Flag.FetchApiAllowed
    )
    QWebEngineUrlScheme.registerScheme(scheme)
    _SCHEME_REGISTERED = True


class MorphismSchemeHandler(QWebEngineUrlSchemeHandler):
    """Serves morphism://app/... static web assets, dynamic MathJax config, and morphism://media/... vault files."""

    MIME_MAP = {
        ".html": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".webp": "image/webp",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".woff": "font/woff",
        ".woff2": "font/woff2",
    }

    def __init__(
        self,
        web_root: Path,
        media_vault: MediaVault,
        config: AppConfig | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.web_root = web_root.resolve()
        self.media_vault = media_vault
        self.config = config or AppConfig()

    def requestStarted(self, job: QWebEngineUrlRequestJob) -> None:
        url = job.requestUrl()
        host = url.host().lower()
        rel_path = url.path().lstrip("/")

        if host == "app" and rel_path == "js/mathjax_init.js":
            tex_cfg = self.config.load_mathjax_tex_config()
            mathjax_obj = {
                "tex": tex_cfg,
                "svg": {"fontCache": "local"},
                "startup": {"typeset": False},
            }
            js_payload = f"window.MathJax = {json.dumps(mathjax_obj, ensure_ascii=False)};\n"
            js_payload += """window.MathJax.startup.ready = function () {
                MathJax.startup.defaultReady();
                MathJax.startup.promise.then(function () {
                    window.dispatchEvent(new Event('morphism-mathjax-ready'));
                });
            };"""
            buf = QBuffer(parent=job)
            buf.setData(QByteArray(js_payload.encode("utf-8")))
            buf.open(QIODevice.OpenModeFlag.ReadOnly)
            job.reply(b"text/javascript; charset=utf-8", buf)
            return

        target_file: Path | None = None
        if host == "app":
            candidate = (self.web_root / rel_path).resolve()
            if str(candidate).startswith(str(self.web_root)) and candidate.is_file():
                target_file = candidate
        elif host == "media":
            target_file = self.media_vault.resolve_path(rel_path)

        if target_file is None or not target_file.exists():
            job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
            return

        try:
            data = target_file.read_bytes()
        except OSError:
            job.fail(QWebEngineUrlRequestJob.Error.RequestFailed)
            return

        ext = target_file.suffix.lower()
        mime = self.MIME_MAP.get(ext)
        if not mime:
            guessed, _ = mimetypes.guess_type(target_file.name)
            mime = guessed or "application/octet-stream"

        buf = QBuffer(parent=job)
        buf.setData(QByteArray(data))
        buf.open(QIODevice.OpenModeFlag.ReadOnly)
        job.reply(mime.encode("utf-8"), buf)
