from __future__ import annotations

from pathlib import Path
import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from morphism_srs.controllers.event_bus import EventBus
from morphism_srs.controllers.review_controller import ReviewController
from morphism_srs.services.mobile_server import EphemeralMobileServer
from morphism_srs.services.qr_generator import render_qr_pixmap
from morphism_srs.storage.media_vault import MediaVault
from morphism_srs.theming.delegates import set_widget_props
from morphism_srs.ui.window_sizing import apply_relative_geometry, wrap_in_scroll_area


class MobileQRDialog(QDialog):
    """
    Dialog that starts the EphemeralMobileServer ONLY while open, displays a scannable QR code,
    and shuts the server down immediately when closed.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        review_controller: ReviewController,
        media_vault: MediaVault,
        web_root: Path,
        event_bus: EventBus,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Mobile Companion — Ephemeral LAN Sync")
        apply_relative_geometry(self, width_ratio=0.50, height_ratio=0.68, min_width=520, min_height=480)

        mathjax_path = web_root / "vendor" / "mathjax" / "tex-svg-full.js"
        mj_bytes = mathjax_path.read_bytes() if mathjax_path.exists() else b""

        self.server = EphemeralMobileServer(
            conn=conn,
            review_controller=review_controller,
            media_vault=media_vault,
            mathjax_js_bytes=mj_bytes,
            event_bus=event_bus,
        )
        url = self.server.start()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        container = QWidget(self)
        root = QVBoxLayout(container)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        title = QLabel("📱 Morphism Mobile ? Sync v3", container)
        set_widget_props(title, role="title")
        root.addWidget(title)

        desc = QLabel(
            "Escanea este código QR desde la App Móvil Morphism SRS (o ingresa la URL de abajo) "
            "para sincronizar tus cursos, notas, grafo DAG y repasos FSRS bidireccionalmente.\n\n"
            "⚠️ IMPORTANTE: Mantén esta ventana ABIERTA en el PC durante la sincronización (el servidor se detiene automáticamente al cerrarla).",
            container,
        )
        desc.setWordWrap(True)
        set_widget_props(desc, role="muted")
        root.addWidget(desc)

        card = QFrame(container)
        set_widget_props(card, role="card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 14, 14, 14)
        card_layout.setSpacing(10)

        status_lbl = QLabel(f"Listening on Port {self.server.port} • Token Authenticated", card)
        set_widget_props(status_lbl, role="badge")
        card_layout.addWidget(status_lbl, 0, Qt.AlignmentFlag.AlignCenter)

        qr_label = QLabel(card)
        qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        qr_pix = render_qr_pixmap(url, module_px=5, border_modules=4)
        qr_label.setPixmap(qr_pix)
        profile_edit = QLineEdit(self.server.profile_name, card)
        profile_edit.setPlaceholderText("Nombre de este perfil / colecci?n")
        def update_profile():
            import json
            name = profile_edit.text().strip()[:80]
            if not name:
                return
            self.server.profile_name = name
            self.server.conn.execute("INSERT OR REPLACE INTO app_meta VALUES ('sync_profile_name', ?)", (json.dumps(name),))
            new_url = self.server.url
            self.url_edit.setText(new_url)
            qr_label.setPixmap(render_qr_pixmap(new_url, module_px=5, border_modules=4))
            status_lbl.setText(f"{name} ? {self.server.db_uuid[:8]} ? AES-256-GCM ? sesi?n de 30 min")
        profile_edit.editingFinished.connect(update_profile)
        card_layout.addWidget(profile_edit)
        card_layout.addWidget(qr_label, 0, Qt.AlignmentFlag.AlignCenter)

        url_row = QHBoxLayout()
        self.url_edit = QLineEdit(url, card)
        self.url_edit.setReadOnly(True)
        copy_btn = QPushButton("Copy URL", card)
        copy_btn.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.url_edit.text()))
        url_row.addWidget(self.url_edit, 1)
        url_row.addWidget(copy_btn)
        card_layout.addLayout(url_row)

        root.addWidget(card)
        root.addStretch(1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        stop_btn = QPushButton("Stop Server & Close", container)
        set_widget_props(stop_btn, variant="danger")
        stop_btn.setMinimumHeight(34)
        stop_btn.clicked.connect(self.accept)
        btn_row.addWidget(stop_btn)
        root.addLayout(btn_row)

        scroll = wrap_in_scroll_area(container, self, min_width=460, min_height=420)
        outer.addWidget(scroll)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.server.stop()
        super().closeEvent(event)

    def done(self, result: int) -> None:
        self.server.stop()
        super().done(result)
