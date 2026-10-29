from __future__ import annotations

import math
from pathlib import Path
import sqlite3

from PySide6.QtCore import QLineF, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QKeyEvent,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QShortcut,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from morphism_srs.config import AppConfig, get_project_root
from morphism_srs.controllers.event_bus import EventBus
from morphism_srs.controllers.explorer_controller import ExplorerController
from morphism_srs.controllers.review_controller import CustomStudyConfig, ReviewController
from morphism_srs.domain.enums import NoteReviewMode
from morphism_srs.domain.models import EdgeModel, NoteMetrics, NoteModel
from morphism_srs.domain.scheduler_engine import SchedulerEngine
from morphism_srs.services.dsl_compiler.compiler import DSLCompiler
from morphism_srs.storage.media_vault import MediaVault
from morphism_srs.storage.repositories.course_repo import CourseRepository
from morphism_srs.storage.repositories.folder_repo import FolderRepository
from morphism_srs.storage.repositories.review_repo import ReviewRepository
from morphism_srs.storage.unit_of_work import UnitOfWork
from morphism_srs.theming.delegates import set_widget_props
from morphism_srs.theming.theme_manager import ThemeManager
from morphism_srs.ui.dialogs.delete_prereqs_dialog import (
    DeleteNoteDialog,
    DeletePrereqsDialog,
)
from morphism_srs.ui.dialogs.node_editor_dialog import NodeEditorDialog
from morphism_srs.ui.dialogs.retrievability_dialog import RetrievabilityDialog
from morphism_srs.ui.window_sizing import wrap_in_scroll_area
from morphism_srs.web_engine.web_profile import WebEngineProfileManager


class GraphEdgeItem(QGraphicsPathItem):
    """
    Directed Bezier edge connecting cardinal ports (North/South/East/West) of two GraphNodeItems
    with a crisp, high-contrast filled arrowhead tip right on the target node's cardinal boundary.
    """

    ARROW_SIZE = 13.5

    def __init__(
        self,
        edge_model: EdgeModel,
        source_item: GraphNodeItem,
        target_item: GraphNodeItem,
        theme_manager: ThemeManager,
    ) -> None:
        super().__init__()
        self.edge_model = edge_model
        self.source_item = source_item
        self.target_item = target_item
        self.theme_manager = theme_manager
        self._tip_point = QPointF()
        self._tip_angle = 0.0
        self.setZValue(0.5)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setEnabled(False)
        self.update_position()

    def boundingRect(self) -> QRectF:
        return super().boundingRect().adjusted(-18.0, -18.0, 18.0, 18.0)

    def update_position(self) -> None:
        p1 = self.source_item.pos()
        p2 = self.target_item.pos()
        dx = p2.x() - p1.x()
        dy = p2.y() - p1.y()

        hw1, hh1 = self.source_item.cardinal_extents()
        hw2, hh2 = self.target_item.cardinal_extents()

        # Choose cardinal attachment ports (East/West vs North/South)
        if abs(dx) >= abs(dy) * 0.85:
            if dx >= 0:
                start_pt = QPointF(p1.x() + hw1, p1.y())
                end_pt = QPointF(p2.x() - hw2, p2.y())
                out_dir = QPointF(1.0, 0.0)
                in_dir = QPointF(1.0, 0.0)
            else:
                start_pt = QPointF(p1.x() - hw1, p1.y())
                end_pt = QPointF(p2.x() + hw2, p2.y())
                out_dir = QPointF(-1.0, 0.0)
                in_dir = QPointF(-1.0, 0.0)
            span = max(45.0, abs(end_pt.x() - start_pt.x()) * 0.45)
            c1 = QPointF(start_pt.x() + out_dir.x() * span, start_pt.y())
            c2 = QPointF(end_pt.x() - in_dir.x() * span, end_pt.y())
        else:
            if dy >= 0:
                start_pt = QPointF(p1.x(), p1.y() + hh1)
                end_pt = QPointF(p2.x(), p2.y() - hh2)
                out_dir = QPointF(0.0, 1.0)
                in_dir = QPointF(0.0, 1.0)
            else:
                start_pt = QPointF(p1.x(), p1.y() - hh1)
                end_pt = QPointF(p2.x(), p2.y() + hh2)
                out_dir = QPointF(0.0, -1.0)
                in_dir = QPointF(0.0, -1.0)
            span = max(45.0, abs(end_pt.y() - start_pt.y()) * 0.45)
            c1 = QPointF(start_pt.x(), start_pt.y() + out_dir.y() * span)
            c2 = QPointF(end_pt.x(), end_pt.y() - in_dir.y() * span)

        self._tip_point = end_pt
        # Compute tangent direction arriving at end_pt (from c2 -> end_pt, fallback to start_pt -> end_pt)
        tx = end_pt.x() - c2.x()
        ty = end_pt.y() - c2.y()
        if abs(tx) < 1e-3 and abs(ty) < 1e-3:
            tx = end_pt.x() - start_pt.x()
            ty = end_pt.y() - start_pt.y()
        self._tip_angle = math.atan2(ty, tx)

        # Pull curve endpoint slightly back so the stroke ends cleanly inside the arrowhead base
        line_end = QPointF(
            end_pt.x() - math.cos(self._tip_angle) * (self.ARROW_SIZE * 0.65),
            end_pt.y() - math.sin(self._tip_angle) * (self.ARROW_SIZE * 0.65),
        )

        path = QPainterPath(start_pt)
        path.cubicTo(c1, c2, line_end)
        self.setPath(path)

    def paint(self, painter: QPainter, _option, widget: QWidget | None = None) -> None:
        scale = painter.worldTransform().m11()
        is_highlighted = self.source_item.isSelected() or self.target_item.isSelected()
        if is_highlighted:
            color = QColor("#facc15")
            pen_width = 2.8
        else:
            color = QColor("#94a3b8")
            pen_width = 2.2

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(color, pen_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if scale < 0.25:
            painter.drawLine(self.source_item.pos(), self.target_item.pos())
            return

        painter.drawPath(self.path())

        # Draw sharp filled arrowhead with tip right at self._tip_point
        tip = self._tip_point
        angle = self._tip_angle
        sz = self.ARROW_SIZE
        wing_angle = math.pi / 6.2
        left_pt = QPointF(
            tip.x() - sz * math.cos(angle - wing_angle),
            tip.y() - sz * math.sin(angle - wing_angle),
        )
        right_pt = QPointF(
            tip.x() - sz * math.cos(angle + wing_angle),
            tip.y() - sz * math.sin(angle + wing_angle),
        )
        back_indent = QPointF(
            tip.x() - (sz * 0.78) * math.cos(angle),
            tip.y() - (sz * 0.78) * math.sin(angle),
        )
        painter.setPen(QPen(color, 1.2))
        painter.setBrush(QBrush(color))
        painter.drawPolygon(QPolygonF([tip, left_pt, back_indent, right_pt]))


class GraphNodeItem(QGraphicsItem):
    """
    Shape-coded & Colorblind-Friendly Filled DAG Node Item:
    - standard -> Rounded Rectangle
    - serial   -> Rhombus / Diamond
    - cloze    -> Circle / Ellipse

    Color Palette (Red vs Blue/Slate — safe for red-green colorblindness):
    - Due cards (> 0)     : Rich Red gradient (#dc2626 -> #7f1d1d) with Coral border (#fca5a5)
    - Learned / Up-to-date: Rich Royal Blue gradient (#2563eb -> #1e3a8a) with Sky Blue border (#60a5fa)
    - Partially learned   : Deep Cyan-Blue gradient (#0284c7 -> #0f172a) with Cyan border (#38bdf8)
    - New / Unreviewed    : Slate gradient (#334155 -> #1e293b) with Silver-Slate border (#94a3b8)
    """

    WIDTH = 216.0
    HEIGHT = 86.0
    DIAMOND_PAD_X = 14.0
    DIAMOND_PAD_Y = 8.0
    GRID_X = 300.0
    GRID_Y = 130.0

    def __init__(
        self,
        note: NoteModel,
        metrics: NoteMetrics,
        theme_manager: ThemeManager,
        explorer_view: ExplorerView,
    ) -> None:
        super().__init__()
        self.note = note
        self.metrics = metrics
        self.theme_manager = theme_manager
        self.explorer_view = explorer_view
        self.connected_edges: list[GraphEdgeItem] = []

        self.setPos(note.pos_x, note.pos_y)
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setZValue(1.0)
        self.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)
        self.setToolTip(
            f"<b>{self.note.title}</b><br>"
            f"Mode: {self.note.review_mode.value.upper()}<br>"
            f"Cards: {self.metrics.card_count} (Due: {self.metrics.due_count}, New: {self.metrics.new_count})<br>"
            f"<i>• Shift+Click two nodes to link prerequisite</i><br>"
            f"<i>• Double-click to study</i>"
        )

    def cardinal_extents(self) -> tuple[float, float]:
        """Return (half_width, half_height) of the exact cardinal attachment points."""
        if self.note.review_mode == NoteReviewMode.SERIAL:
            return (self.WIDTH / 2.0 + self.DIAMOND_PAD_X, self.HEIGHT / 2.0 + self.DIAMOND_PAD_Y)
        return (self.WIDTH / 2.0, self.HEIGHT / 2.0)

    def boundingRect(self) -> QRectF:
        hw, hh = self.cardinal_extents()
        pad = 2.0
        return QRectF(-hw - pad, -hh - pad, (hw + pad) * 2.0, (hh + pad) * 2.0)

    def shape(self) -> QPainterPath:
        rect = QRectF(-self.WIDTH / 2.0, -self.HEIGHT / 2.0, self.WIDTH, self.HEIGHT)
        path = QPainterPath()
        if self.note.review_mode == NoteReviewMode.SERIAL:
            hw, hh = self.cardinal_extents()
            poly = QPolygonF(
                [
                    QPointF(0.0, -hh),
                    QPointF(hw, 0.0),
                    QPointF(0.0, hh),
                    QPointF(-hw, 0.0),
                ]
            )
            path.addPolygon(poly)
            path.closeSubpath()
        elif self.note.review_mode == NoteReviewMode.CLOZE:
            path.addEllipse(rect)
        else:
            path.addRoundedRect(rect, 12.0, 12.0)
        return path

    def _resolve_colors(self) -> tuple[QColor, QColor, QColor, float, str]:
        """Returns (grad_top, grad_bottom, border_color, border_width, status_label)."""
        if self.metrics.due_count > 0:
            top = QColor("#dc2626")
            bot = QColor("#7f1d1d")
            border = QColor("#fca5a5")
            width = 3.2
            status = f"DUE ({self.metrics.due_count})"
        elif self.metrics.is_incomplete:
            # Grey node: incomplete initial study (cards in new or learning)
            top = QColor("#475569")
            bot = QColor("#334155")
            border = QColor("#94a3b8")
            width = 2.5
            if self.metrics.new_count > 0 and self.metrics.new_count == self.metrics.card_count:
                status = f"NEW ({self.metrics.card_count})"
            else:
                status = f"LEARNING ({self.metrics.card_count - self.metrics.new_count}/{self.metrics.card_count})"
        else:
            # Completed initial study (in regular review cycle)
            top = QColor("#2563eb")
            bot = QColor("#1e3a8a")
            border = QColor("#93c5fd")
            width = 3.0
            status = f"R_min {int(self.metrics.r_min * 100)}%"

        if self.isSelected():
            border = QColor("#facc15")
            width = 4.0

        return top, bot, border, width, status

    def paint(self, painter: QPainter, _option, widget: QWidget | None = None) -> None:
        scale = painter.worldTransform().m11()
        top_col, bot_col, border_col, pen_width, status_txt = self._resolve_colors()

        _, hh = self.cardinal_extents()
        grad = QLinearGradient(0.0, -hh, 0.0, hh)
        grad.setColorAt(0.0, top_col)
        grad.setColorAt(1.0, bot_col)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(QBrush(grad))
        painter.setPen(QPen(border_col, pen_width))
        painter.drawPath(self.shape())

        if scale < 0.30:
            return

        title_rect = QRectF(-self.WIDTH / 2.0 + 16.0, -self.HEIGHT / 2.0 + 10.0, self.WIDTH - 32.0, 38.0)
        font = QFont("Segoe UI", 10)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#f8fafc"))
        elided = painter.fontMetrics().elidedText(
            self.note.title, Qt.TextElideMode.ElideRight, int(title_rect.width())
        )
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, elided)

        if scale >= 0.55:
            sub_rect = QRectF(-self.WIDTH / 2.0 + 18.0, 10.0, self.WIDTH - 36.0, 22.0)
            sub_font = QFont("Segoe UI", 8)
            sub_font.setBold(True)
            painter.setFont(sub_font)
            painter.setPen(QColor("#e2e8f0"))
            mode_tag = self.note.review_mode.value.upper()
            painter.drawText(
                sub_rect,
                Qt.AlignmentFlag.AlignCenter,
                f"{mode_tag} • {status_txt}",
            )

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and self.scene() is not None:
            if self.explorer_view.snapping_enabled:
                sel = [it for it in self.scene().selectedItems() if isinstance(it, GraphNodeItem)]
                if len(sel) > 1:
                    return value
                new_pos: QPointF = value
                snapped_x = round(new_pos.x() / self.GRID_X) * self.GRID_X
                snapped_y = round(new_pos.y() / self.GRID_Y) * self.GRID_Y
                return QPointF(snapped_x, snapped_y)
        elif change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            for e in self.connected_edges:
                e.update_position()
        return super().itemChange(change, value)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.note.id is not None:
            event.accept()
            self.explorer_view.study_note(self.note.id, force=False)
            return
        super().mouseDoubleClickEvent(event)


class GraphCanvasView(QGraphicsView):
    """
    Interactive QGraphicsView supporting:
    - Hand Pan Mode (✋): Left-click & drag pans the viewport, double-click a node studies it.
    - Bulk Select Mode (🔲): Left-click & drag draws a RubberBand marquee to bulk-select nodes.
    - Interactive Prerequisite Linking (Right-click -> Add Prerequisite or Shift+Click).
    """

    def __init__(self, scene: QGraphicsScene, explorer_view: ExplorerView) -> None:
        super().__init__(scene, explorer_view)
        self.explorer_view = explorer_view
        self.setMinimumSize(420, 300)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.BoundingRectViewportUpdate)
        self.setSceneRect(-25000, -25000, 50000, 50000)

        self._middle_panning = False
        self._pan_start = QPointF()
        self._drag_start_positions: dict[int, tuple[float, float]] = {}
        self._shift_link_source_id: int | None = None

        # Interactive Prerequisite Linking Mode (from Right-Click -> Add Prerequisite)
        self.prereq_target_node: GraphNodeItem | None = None
        self.temp_prereq_line: QGraphicsLineItem | None = None

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self.explorer_view, "floating_bar") and self.explorer_view.floating_bar is not None:
            fb = self.explorer_view.floating_bar
            fb.adjustSize()
            fb.move((self.viewport().width() - fb.width()) // 2, 14)

    def _node_at_viewport_pos(self, pos: QPoint) -> GraphNodeItem | None:
        scene_pt = self.mapToScene(pos)
        for it in self.scene().items(scene_pt):
            if isinstance(it, GraphNodeItem):
                return it
        return None

    def set_hand_pan_mode(self, hand_pan: bool) -> None:
        if hand_pan:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        else:
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)

    def start_prereq_linking_mode(self, target_node: GraphNodeItem) -> None:
        """Click any parent node to connect clicked_parent -> target_node."""
        self.cancel_prereq_linking_mode()
        self.prereq_target_node = target_node
        self.setCursor(Qt.CursorShape.CrossCursor)
        p = target_node.pos()
        self.temp_prereq_line = QGraphicsLineItem(QLineF(p, p))
        pen = QPen(QColor("#facc15"), 2.5, Qt.PenStyle.DashLine)
        self.temp_prereq_line.setPen(pen)
        self.temp_prereq_line.setZValue(10.0)
        self.temp_prereq_line.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.temp_prereq_line.setEnabled(False)
        self.scene().addItem(self.temp_prereq_line)
        self.explorer_view.event_bus.status_message.emit(
            f"Click a prerequisite node to link it into '{target_node.note.title}' (Right-click or Esc to cancel).",
            5000,
        )

    def cancel_prereq_linking_mode(self) -> None:
        if self.temp_prereq_line is not None and self.temp_prereq_line.scene() is not None:
            self.scene().removeItem(self.temp_prereq_line)
        self.temp_prereq_line = None
        self.prereq_target_node = None
        self.unsetCursor()

    def wheelEvent(self, event: QWheelEvent) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else (1.0 / 1.15)
        curr_scale = self.transform().m11()
        if (curr_scale < 0.15 and factor < 1.0) or (curr_scale > 3.5 and factor > 1.0):
            return
        self.scale(factor, factor)

    def mousePressEvent(self, event) -> None:
        if self.prereq_target_node is not None:
            if event.button() == Qt.MouseButton.LeftButton:
                item = self._node_at_viewport_pos(event.position().toPoint())
                if (
                    item is not None
                    and item is not self.prereq_target_node
                    and item.note.id is not None
                    and self.prereq_target_node.note.id is not None
                ):
                    src_id = item.note.id
                    dst_id = self.prereq_target_node.note.id
                    self.cancel_prereq_linking_mode()
                    self.explorer_view.create_prerequisite_edge(src_id, dst_id)
                    event.accept()
                    return
            self.cancel_prereq_linking_mode()
            event.accept()
            return

        if event.button() == Qt.MouseButton.MiddleButton:
            self._middle_panning = True
            self._pan_start = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return

        item = self._node_at_viewport_pos(event.position().toPoint())
        if item is not None and (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            if self._shift_link_source_id is None and item.note.id is not None:
                self._shift_link_source_id = item.note.id
                self.start_prereq_linking_mode(item)
                self.explorer_view.event_bus.status_message.emit(
                    f"Linking from '{item.note.title}' — Click destination node to connect prerequisite edge.",
                    5000,
                )
            elif self._shift_link_source_id is not None and item.note.id is not None:
                src_id = self._shift_link_source_id
                self._shift_link_source_id = None
                self.cancel_prereq_linking_mode()
                if src_id != item.note.id:
                    self.explorer_view.create_prerequisite_edge(src_id, item.note.id)
            event.accept()
            return

        self._shift_link_source_id = None
        self._drag_start_positions = {
            it.note.id: (it.pos().x(), it.pos().y())
            for it in self.scene().items()
            if isinstance(it, GraphNodeItem) and it.note.id is not None
        }
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self.prereq_target_node is not None and self.temp_prereq_line is not None:
            scene_pt = self.mapToScene(event.position().toPoint())
            self.temp_prereq_line.setLine(QLineF(scene_pt, self.prereq_target_node.pos()))
            event.accept()
            return

        if self._middle_panning:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(delta.y()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton and self._middle_panning:
            self._middle_panning = False
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

        moved_old: dict[int, tuple[float, float]] = {}
        moved_new: dict[int, tuple[float, float]] = {}
        for it in self.scene().items():
            if isinstance(it, GraphNodeItem) and it.note.id is not None:
                nid = it.note.id
                old_xy = self._drag_start_positions.get(nid)
                new_xy = (it.pos().x(), it.pos().y())
                if old_xy and (abs(old_xy[0] - new_xy[0]) > 1.0 or abs(old_xy[1] - new_xy[1]) > 1.0):
                    moved_old[nid] = old_xy
                    moved_new[nid] = new_xy
        if moved_new and self.explorer_view.current_course_id is not None:
            self.explorer_view.explorer_controller.record_nodes_moved(
                self.explorer_view.current_course_id,
                moved_old,
                moved_new,
            )

    def mouseDoubleClickEvent(self, event) -> None:
        item = self.itemAt(event.position().toPoint())
        if isinstance(item, GraphNodeItem) and item.note.id is not None:
            event.accept()
            self.explorer_view.study_note(item.note.id, force=False)
            return
        super().mouseDoubleClickEvent(event)


class ExplorerView(QWidget):
    """
    DAG Knowledge Graph Explorer:
    - Filled colorblind-safe Red (Due) vs Blue (Learned) vs Slate (New) nodes with thick borders
    - Cardinal port arrows with visible arrowheads
    - Right-side vertical toolbar with Magnet Snapping toggle (🧲) and Hand Pan / Marquee Select toggle (✋ / 🔲)
    - Double-click node = Study Note (with DAG prerequisite check); Right-click = Force Study, Edit, Add/Remove Prereqs, etc.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        config: AppConfig,
        media_vault: MediaVault,
        web_profile: WebEngineProfileManager,
        theme_manager: ThemeManager,
        explorer_controller: ExplorerController,
        review_controller: ReviewController,
        event_bus: EventBus,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.conn = conn
        self.config = config
        self.media_vault = media_vault
        self.web_profile = web_profile
        self.theme_manager = theme_manager
        self.explorer_controller = explorer_controller
        self.review_controller = review_controller
        self.event_bus = event_bus

        self.course_repo = CourseRepository(conn)
        self.folder_repo = FolderRepository(conn)
        self.review_repo = ReviewRepository(conn)

        self.current_course_id: int | None = None
        self.snapping_enabled: bool = False
        self.hand_pan_mode: bool = True
        self._node_items: dict[int, GraphNodeItem] = {}
        self._edges: list[EdgeModel] = []
        self._metrics_map: dict[int, NoteMetrics] = {}

        self._build_ui()
        self.event_bus.course_selected.connect(self.select_course)
        self.event_bus.courses_updated.connect(self._reload_course_combo)
        self.event_bus.notes_updated.connect(self._on_notes_updated)
        self.event_bus.review_state_changed.connect(self.rebuild_graph)
        self.event_bus.open_node_in_explorer.connect(self._on_focus_node)
        self.theme_manager.theme_changed.connect(lambda _: self.scene.update())

        self._reload_course_combo()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        container = QWidget(self)
        root = QVBoxLayout(container)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        # Clean Top Toolbar without redundant course selector or export
        toolbar = QHBoxLayout()
        self.course_title_lbl = QLabel("No Course Selected", container)
        set_widget_props(self.course_title_lbl, role="title")
        toolbar.addWidget(self.course_title_lbl)
        toolbar.addSpacing(8)

        new_node_btn = QPushButton("+ New Note", container)
        set_widget_props(new_node_btn, variant="primary")
        new_node_btn.clicked.connect(self._on_create_note_center)
        toolbar.addWidget(new_node_btn)

        layout_btn = QPushButton("⚠️ Auto-Layout DAG", container)
        set_widget_props(layout_btn, variant="danger")
        layout_btn.setToolTip("Warning: Recomputes and overwrites manual node positions in this course")
        layout_btn.clicked.connect(self._on_auto_layout)
        toolbar.addWidget(layout_btn)

        undo_btn = QPushButton("↩ Undo (Ctrl+Z)", container)
        set_widget_props(undo_btn, variant="ghost")
        undo_btn.clicked.connect(lambda: self.explorer_controller.undo_last_action())
        toolbar.addWidget(undo_btn)

        toolbar.addStretch(1)

        # Prominent Filter QLineEdit with secondary styling
        self.quick_search = QLineEdit(container)
        self.quick_search.setPlaceholderText("🔍 Filter notes by title or tag (Ctrl+F)...")
        self.quick_search.setClearButtonEnabled(True)
        self.quick_search.setMinimumWidth(260)
        set_widget_props(self.quick_search, role="filter", variant="secondary")
        self.quick_search.textChanged.connect(self._on_quick_filter_changed)
        toolbar.addWidget(self.quick_search)

        find_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        find_shortcut.activated.connect(self.quick_search.setFocus)

        root.addLayout(toolbar)

        # Main Center Area: Canvas on Left + Dedicated Vertical Mode Toolbar on Right
        canvas_row = QHBoxLayout()
        canvas_row.setSpacing(8)

        self.scene = QGraphicsScene(container)
        self.scene.selectionChanged.connect(self._on_selection_changed)
        self.canvas = GraphCanvasView(self.scene, self)
        self.canvas.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.canvas.customContextMenuRequested.connect(self._on_canvas_context_menu)
        canvas_row.addWidget(self.canvas, 1)

        # Floating Bulk Action Bar (overlay inside canvas so showing/hiding does not shift canvas layout)
        self.floating_bar = QFrame(self.canvas)
        set_widget_props(self.floating_bar, role="floating_bar")
        fb_layout = QHBoxLayout(self.floating_bar)
        fb_layout.setContentsMargins(12, 6, 12, 6)
        self.sel_count_lbl = QLabel("0 nodes selected", self.floating_bar)
        set_widget_props(self.sel_count_lbl, role="subtitle")
        fb_layout.addWidget(self.sel_count_lbl)
        fb_layout.addStretch(1)

        study_sub_btn = QPushButton("▶️ Study Selected Subgraph", self.floating_bar)
        set_widget_props(study_sub_btn, variant="primary")
        study_sub_btn.clicked.connect(self._on_bulk_study_subgraph)
        fb_layout.addWidget(study_sub_btn)

        tag_sub_btn = QPushButton("+ Bulk Tag", self.floating_bar)
        tag_sub_btn.clicked.connect(self._on_bulk_add_tag)
        fb_layout.addWidget(tag_sub_btn)

        layout_sub_btn = QPushButton("Auto-Layout Selected", self.floating_bar)
        layout_sub_btn.clicked.connect(self._on_bulk_layout)
        fb_layout.addWidget(layout_sub_btn)

        susp_sub_btn = QPushButton("Suspend Selected", self.floating_bar)
        fb_layout.addWidget(susp_sub_btn)
        susp_sub_btn.clicked.connect(lambda: self._on_bulk_suspend(True))

        del_sub_btn = QPushButton("🗑️ Delete Selected", self.floating_bar)
        set_widget_props(del_sub_btn, variant="danger")
        del_sub_btn.clicked.connect(self._on_bulk_delete)
        fb_layout.addWidget(del_sub_btn)

        self.floating_bar.setVisible(False)

        # Right-Side Vertical Toolbar for Snapping (🧲) and Hand/Selection Mode (✋ / 🔲)
        right_bar = QFrame(container)
        set_widget_props(right_bar, role="panel")
        right_bar.setFixedWidth(136)
        rb_layout = QVBoxLayout(right_bar)
        rb_layout.setContentsMargins(8, 10, 8, 10)
        rb_layout.setSpacing(8)

        rb_title = QLabel("<b>Canvas Tools</b>", right_bar)
        rb_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rb_layout.addWidget(rb_title)

        # Toggle 1: Magnet Snapping
        self.snap_btn = QPushButton("🧲 Snap: OFF", right_bar)
        self.snap_btn.setCheckable(True)
        self.snap_btn.setChecked(False)
        self.snap_btn.setMinimumHeight(36)
        self.snap_btn.setToolTip("Toggle grid snapping when dragging nodes")
        self.snap_btn.toggled.connect(self._on_toggle_snapping)
        rb_layout.addWidget(self.snap_btn)

        # Toggle 2: Hand Pan vs Bulk Select Mode
        self.mode_btn = QPushButton("✋ Pan Mode", right_bar)
        self.mode_btn.setCheckable(True)
        self.mode_btn.setChecked(True)
        self.mode_btn.setMinimumHeight(36)
        set_widget_props(self.mode_btn, variant="primary")
        self.mode_btn.setToolTip(
            "Checked (✋ Pan Mode): Click & drag moves the canvas; double-click node to study.\n"
            "Unchecked (🔲 Select Mode): Click & drag selects multiple nodes in bulk."
        )
        self.mode_btn.toggled.connect(self._on_toggle_hand_mode)
        rb_layout.addWidget(self.mode_btn)

        rb_layout.addSpacing(8)
        zoom_in_btn = QPushButton("🔍 Zoom In", right_bar)
        zoom_in_btn.clicked.connect(lambda: self.canvas.scale(1.2, 1.2))
        rb_layout.addWidget(zoom_in_btn)

        zoom_out_btn = QPushButton("🔍 Zoom Out", right_bar)
        zoom_out_btn.clicked.connect(lambda: self.canvas.scale(1.0 / 1.2, 1.0 / 1.2))
        rb_layout.addWidget(zoom_out_btn)

        fit_btn = QPushButton("🎯 Fit View", right_bar)
        fit_btn.clicked.connect(self._on_fit_view)
        rb_layout.addWidget(fit_btn)

        rb_layout.addStretch(1)
        canvas_row.addWidget(right_bar)
        root.addLayout(canvas_row, 1)

        scroll = wrap_in_scroll_area(container, self, min_width=640, min_height=420)
        outer.addWidget(scroll)

    def _on_toggle_snapping(self, checked: bool) -> None:
        self.snapping_enabled = checked
        if checked:
            self.snap_btn.setText("🧲 Snap: ON")
            set_widget_props(self.snap_btn, variant="primary")
        else:
            self.snap_btn.setText("🧲 Snap: OFF")
            set_widget_props(self.snap_btn, variant="")

    def _on_toggle_hand_mode(self, checked: bool) -> None:
        self.hand_pan_mode = checked
        self.canvas.set_hand_pan_mode(checked)
        if checked:
            self.mode_btn.setText("✋ Pan Mode")
            set_widget_props(self.mode_btn, variant="primary")
        else:
            self.mode_btn.setText("🔲 Bulk Select")
            set_widget_props(self.mode_btn, variant="")
        for it in self._node_items.values():
            it.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, it.isSelected() and not checked)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.canvas.cancel_prereq_linking_mode()
            return
        if (event.modifiers() & Qt.KeyboardModifier.ControlModifier) and event.key() == Qt.Key.Key_Z:
            self.explorer_controller.undo_last_action()
            return
        if event.key() == Qt.Key.Key_Delete:
            self._on_bulk_delete()
            return
        super().keyPressEvent(event)

    def _reload_course_combo(self) -> None:
        courses = self.course_repo.list_all()
        if self.current_course_id is None and courses and courses[0].id is not None:
            self.current_course_id = courses[0].id
        if self.current_course_id is not None:
            c = self.course_repo.get_by_id(self.current_course_id)
            if c:
                self.course_title_lbl.setText(f"📘 {c.name}")
        self.rebuild_graph()

    def select_course(self, course_id: int) -> None:
        self.current_course_id = course_id
        c = self.course_repo.get_by_id(course_id)
        if c:
            self.course_title_lbl.setText(f"📘 {c.name}")
        self.rebuild_graph()

    def _on_notes_updated(self, course_id: int) -> None:
        if course_id == self.current_course_id:
            self.rebuild_graph()

    def rebuild_graph(self) -> None:
        self.canvas.cancel_prereq_linking_mode()
        self.scene.clear()
        self._node_items.clear()
        self._edges.clear()
        self._metrics_map.clear()
        if self.current_course_id is None:
            return

        notes, edges, metrics_map = self.explorer_controller.get_course_graph(self.current_course_id)
        self._edges = list(edges)
        self._metrics_map = dict(metrics_map)

        for n in notes:
            if n.id is None:
                continue
            m = metrics_map.get(n.id) or NoteMetrics(n.id, 0, 0.0, 0.0, 0.0, 0, 0)
            node_item = GraphNodeItem(n, m, self.theme_manager, self)
            self.scene.addItem(node_item)
            self._node_items[n.id] = node_item

        for e in edges:
            src_it = self._node_items.get(e.source_note_id)
            dst_it = self._node_items.get(e.target_note_id)
            if src_it and dst_it:
                edge_item = GraphEdgeItem(e, src_it, dst_it, self.theme_manager)
                src_it.connected_edges.append(edge_item)
                dst_it.connected_edges.append(edge_item)
                self.scene.addItem(edge_item)

    def _selected_note_ids(self) -> list[int]:
        ids: list[int] = []
        for it in self.scene.selectedItems():
            try:
                if isinstance(it, GraphNodeItem) and it.note.id is not None:
                    ids.append(it.note.id)
            except RuntimeError:
                continue
        return ids

    def _on_selection_changed(self) -> None:
        sel = self._selected_note_ids()
        if len(sel) >= 2:
            self.sel_count_lbl.setText(f"{len(sel)} nodes selected")
            self.floating_bar.adjustSize()
            self.floating_bar.move((self.canvas.viewport().width() - self.floating_bar.width()) // 2, 14)
            self.floating_bar.setVisible(True)
            self.floating_bar.raise_()
        else:
            self.floating_bar.setVisible(False)

        for it in list(self._node_items.values()):
            try:
                it.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
            except RuntimeError:
                pass

    def _on_create_note_center(self) -> None:
        center_pt = self.canvas.mapToScene(self.canvas.viewport().rect().center())
        self.create_note_at((center_pt.x(), center_pt.y()))

    def create_note_at(self, pos: tuple[float, float]) -> None:
        if self.current_course_id is None:
            return
        if self.snapping_enabled:
            pos = (
                round(pos[0] / GraphNodeItem.GRID_X) * GraphNodeItem.GRID_X,
                round(pos[1] / GraphNodeItem.GRID_Y) * GraphNodeItem.GRID_Y,
            )
        dlg = NodeEditorDialog(
            conn=self.conn,
            config=self.config,
            media_vault=self.media_vault,
            web_profile=self.web_profile,
            course_id=self.current_course_id,
            note=None,
            default_pos=pos,
            parent=self,
        )
        if dlg.exec():
            self.event_bus.notes_updated.emit(self.current_course_id)
            self.event_bus.courses_updated.emit()

    def open_note_editor(self, note_id: int) -> None:
        if self.current_course_id is None:
            return
        note = self.explorer_controller.note_repo.get_by_id(note_id, include_children=True)
        if note is None:
            return
        dlg = NodeEditorDialog(
            conn=self.conn,
            config=self.config,
            media_vault=self.media_vault,
            web_profile=self.web_profile,
            course_id=self.current_course_id,
            note=note,
            parent=self,
        )
        if dlg.exec():
            self.event_bus.notes_updated.emit(self.current_course_id)

    def _get_locked_prerequisite_titles(self, note_id: int) -> list[str]:
        """
        Checks direct incoming prerequisite notes (parent -> note_id).
        A prerequisite is considered not unlocked if it still has unreviewed (NEW) cards
        or currently overdue (DUE) cards.
        """
        locked_titles: list[str] = []
        for e in self._edges:
            if e.target_note_id == note_id:
                parent_id = e.source_note_id
                parent_item = self._node_items.get(parent_id)
                parent_metrics = self._metrics_map.get(parent_id)
                if parent_item and parent_metrics:
                    if parent_metrics.card_count > 0 and (
                        parent_metrics.new_count > 0 or parent_metrics.due_count > 0
                    ):
                        locked_titles.append(parent_item.note.title)
        return locked_titles

    def study_note(self, note_id: int, force: bool = False) -> None:
        """
        Primary study entry point when double-clicking a node or selecting Study / Force Study.
        """
        if not force:
            locked = self._get_locked_prerequisite_titles(note_id)
            if locked:
                bullets = "\n".join(f"• {t}" for t in locked[:10])
                QMessageBox.warning(
                    self,
                    "Prerequisites Locked",
                    f"Warning: You have not unlocked all prerequisites for this note.\n\n"
                    f"Pending prerequisites:\n{bullets}\n\n"
                    f"(Tip: Right-click the node and choose '⚡ Force Study' to study it anyway.)",
                )
                return

        count = self.review_controller.start_note_study(note_id, force_all_cards=force)
        if count == 0:
            QMessageBox.information(self, "No Cards", "This note does not have any active cards to study.")
            return
        self.event_bus.navigate_to_tab.emit("review")

    def create_prerequisite_edge(self, source_id: int, target_id: int) -> None:
        if self.current_course_id is None:
            return
        edge = self.explorer_controller.create_edge(self.current_course_id, source_id, target_id)
        if edge is None:
            QMessageBox.warning(
                self,
                "Invalid Prerequisite Link",
                "Could not create link (duplicate edge or cycle detected in DAG).",
            )

    def _on_remove_prerequisites_dialog(self, note_id: int) -> None:
        if self.current_course_id is None:
            return
        node_item = self._node_items.get(note_id)
        if node_item is None:
            return

        edge_choices: list[tuple[int, int, str]] = []
        for e in self._edges:
            if e.target_note_id == note_id:
                src_node = self._node_items.get(e.source_note_id)
                src_title = src_node.note.title if src_node else f"Note #{e.source_note_id}"
                edge_choices.append(
                    (e.source_note_id, e.target_note_id, f"Incoming Prerequisite: '{src_title}' → '{node_item.note.title}'")
                )
            elif e.source_note_id == note_id:
                dst_node = self._node_items.get(e.target_note_id)
                dst_title = dst_node.note.title if dst_node else f"Note #{e.target_note_id}"
                edge_choices.append(
                    (e.source_note_id, e.target_note_id, f"Outgoing Dependent: '{node_item.note.title}' → '{dst_title}'")
                )

        if not edge_choices:
            QMessageBox.information(self, "No Links", "This note has no attached prerequisite links.")
            return

        dlg = DeletePrereqsDialog(node_item.note.title, edge_choices, parent=self)
        if dlg.exec():
            for src_id, dst_id in dlg.selected_edges():
                self.explorer_controller.delete_edge(self.current_course_id, src_id, dst_id)

    def _on_reschedule_note(self, note_id: int) -> None:
        note = self.explorer_controller.note_repo.get_by_id(note_id, include_children=True)
        if note is None:
            return
        course = self.course_repo.get_by_id(note.course_id) if note.course_id else None
        retention = note.desired_retention or (course.desired_retention if course else 0.80)
        weights = self.folder_repo.resolve_effective_fsrs_weights(course.folder_id if course else None)
        engine = SchedulerEngine(desired_retention=retention, weights_json=weights)

        replayed = 0
        with UnitOfWork(self.conn):
            for c in note.cards:
                if c.id is None:
                    continue
                logs = self.review_repo.list_logs_for_card(c.id)
                if logs:
                    new_sched = engine.reschedule_from_logs(c.id, logs, c.schedule)
                    self.explorer_controller.card_repo.update_schedule(new_sched)
                    replayed += 1
        self.rebuild_graph()
        QMessageBox.information(
            self,
            "Note Rescheduled",
            f"Recomputed FSRS v5 schedules from review history for {replayed} card(s) in '{note.title}'.",
        )

    def _on_auto_layout(self) -> None:
        if self.current_course_id is None:
            return
        reply = QMessageBox.warning(
            self,
            "⚠️ Confirm Auto-Layout DAG",
            "Warning: Auto-Layout DAG will overwrite the manual positions of all unpinned nodes in this course.\n\n"
            "This can ruin a carefully arranged course layout! Are you sure you want to proceed?\n"
            "(You can press Ctrl+Z afterward to undo.)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.explorer_controller.auto_layout_course(self.current_course_id)
        self._on_fit_view()

    def _on_fit_view(self) -> None:
        rect = self.scene.itemsBoundingRect()
        if not rect.isNull():
            self.canvas.fitInView(rect.adjusted(-90, -90, 90, 90), Qt.AspectRatioMode.KeepAspectRatio)

    def _on_focus_node(self, course_id: int, note_id: int) -> None:
        self.select_course(course_id)
        node_item = self._node_items.get(note_id)
        if node_item:
            self.scene.clearSelection()
            node_item.setSelected(True)
            self.canvas.centerOn(node_item)

    def _on_bulk_study_subgraph(self) -> None:
        sel = self._selected_note_ids()
        if not sel:
            return
        cfg = CustomStudyConfig(
            note_ids=sel,
            include_prerequisite_ancestors=True,
            only_due_or_new=False,
            sort_criterion="topological_due",
        )
        cnt = self.review_controller.start_custom_study(cfg)
        if cnt > 0:
            self.event_bus.navigate_to_tab.emit("review")

    def _on_bulk_add_tag(self) -> None:
        sel = self._selected_note_ids()
        if not sel or self.current_course_id is None:
            return
        tag, ok = QInputDialog.getText(self, "Bulk Add Tag", "Tag name (snake_case):")
        if ok and tag.strip():
            self.explorer_controller.bulk_add_tag(self.current_course_id, sel, tag.strip())

    def _on_bulk_layout(self) -> None:
        sel = self._selected_note_ids()
        if sel and self.current_course_id is not None:
            self.explorer_controller.auto_layout_course(self.current_course_id, note_ids_subset=sel)

    def _on_bulk_suspend(self, suspended: bool) -> None:
        sel = self._selected_note_ids()
        if sel and self.current_course_id is not None:
            self.explorer_controller.bulk_suspend_notes(self.current_course_id, sel, suspended)

    def _on_quick_filter_changed(self, text: str) -> None:
        q = text.strip().lower()
        first_match = None
        for nid, item in self._node_items.items():
            if not q:
                item.setOpacity(1.0)
            else:
                matches = q in item.note.title.lower() or any(q in t.lower() for t in item.note.tags)
                item.setOpacity(1.0 if matches else 0.22)
                if matches and first_match is None:
                    first_match = item
        if first_match is not None:
            self.canvas.centerOn(first_match)

    def _on_export_current_course(self) -> None:
        if self.current_course_id is None:
            QMessageBox.information(self, "No Course", "Please select a course to export.")
            return
        course = self.course_repo.get_by_id(self.current_course_id)
        if not course:
            return
        fmt_choices = ["Morphism DSL (.mdsl)", "Morphism Package (.mpkg)", "Course JSON (.json)"]
        chosen_fmt_str, ok = QInputDialog.getItem(
            self,
            f"Export '{course.name}'",
            "Choose export format:",
            fmt_choices,
            0,
            False,
        )
        if not ok or not chosen_fmt_str:
            return
        fmt = "mdsl" if "mdsl" in chosen_fmt_str else ("mpkg" if "mpkg" in chosen_fmt_str else "json")
        safe_name = course.name.replace(" ", "_").lower()
        export_dir = get_project_root() / "to_export"
        export_dir.mkdir(parents=True, exist_ok=True)
        default_file = str(export_dir / f"{safe_name}.{fmt}")

        if fmt == "mpkg":
            path_str, _ = QFileDialog.getSaveFileName(self, "Export .mpkg Deck", default_file, "Morphism Package (*.mpkg)")
            if path_str:
                from morphism_srs.services.import_export.mpkg_service import MpkgService
                MpkgService(self.conn, self.media_vault).export_mpkg(self.current_course_id, Path(path_str), include_scheduling=True)
                QMessageBox.information(self, "Export Complete", f"Exported course to '{path_str}'.")
        elif fmt == "json":
            path_str, _ = QFileDialog.getSaveFileName(self, "Export .json Deck", default_file, "JSON (*.json)")
            if path_str:
                from morphism_srs.services.import_export.json_service import JsonImportExportService
                JsonImportExportService(self.conn).export_course_file(self.current_course_id, Path(path_str), include_scheduling=True)
                QMessageBox.information(self, "Export Complete", f"Exported course to '{path_str}'.")
        elif fmt == "mdsl":
            path_str, _ = QFileDialog.getSaveFileName(self, "Export .mdsl Source", default_file, "Morphism DSL (*.mdsl)")
            if path_str:
                notes = self.explorer_controller.note_repo.list_by_course(self.current_course_id, include_children=True)
                edges = self.explorer_controller.note_repo.list_edges_by_course(self.current_course_id)
                mdsl_str = DSLCompiler.decompile_course(course, notes, edges)
                Path(path_str).write_text(mdsl_str, encoding="utf-8")
                QMessageBox.information(self, "Export Complete", f"Exported course to '{path_str}'.")

    def _on_bulk_delete(self) -> None:
        sel = self._selected_note_ids()
        if not sel or self.current_course_id is None:
            return
        dlg = DeleteNoteDialog(note_count=len(sel), parent=self)
        if dlg.exec():
            self.scene.clearSelection()
            if dlg.is_unlink_only:
                with UnitOfWork(self.conn):
                    for nid in sel:
                        self.explorer_controller.note_repo.unlink_from_course(self.current_course_id, nid)
                self.event_bus.notes_updated.emit(self.current_course_id)
                self.event_bus.courses_updated.emit()
                self.event_bus.status_message.emit(
                    f"Unlinked {len(sel)} note(s) from this course (preserved in database and Note Browser).",
                    4000,
                )
            else:
                self.explorer_controller.bulk_delete_notes(self.current_course_id, sel, bridge_edges=dlg.bridge_edges)
                self.event_bus.courses_updated.emit()

    def _on_canvas_context_menu(self, pos) -> None:
        item = self.canvas._node_at_viewport_pos(pos)
        menu = QMenu(self)
        if isinstance(item, GraphNodeItem) and item.note.id is not None:
            nid = item.note.id
            study_act = menu.addAction("▶️ Study Note")
            force_study_act = menu.addAction("⚡ Force Study (Ignore Prerequisites)")
            menu.addSeparator()
            edit_act = menu.addAction("✏️ Edit Note")
            metrics_act = menu.addAction("📈 Info / Retrievability Plot")
            menu.addSeparator()
            add_prereq_act = menu.addAction("🔗 Add Prerequisite (or Shift+Click 2 nodes)")
            rm_prereq_act = menu.addAction("✂️ Remove Prerequisites...")
            resched_act = menu.addAction("🔄 Reschedule Note FSRS State")
            menu.addSeparator()
            unlink_act = menu.addAction("🔗 Unlink from Course (Soft-Delete)")
            del_act = menu.addAction("🗑️ Delete Permanently from Database")

            chosen = menu.exec(self.canvas.viewport().mapToGlobal(pos))
            if chosen == study_act:
                self.study_note(nid, force=False)
            elif chosen == force_study_act:
                self.study_note(nid, force=True)
            elif chosen == edit_act:
                self.open_note_editor(nid)
            elif chosen == metrics_act:
                RetrievabilityDialog(self.conn, self.web_profile, nid, parent=self).exec()
            elif chosen == add_prereq_act:
                self.canvas.start_prereq_linking_mode(item)
            elif chosen == rm_prereq_act:
                self._on_remove_prerequisites_dialog(nid)
            elif chosen == resched_act:
                self._on_reschedule_note(nid)
            elif chosen == unlink_act:
                if self.current_course_id is not None:
                    with UnitOfWork(self.conn):
                        self.explorer_controller.note_repo.unlink_from_course(self.current_course_id, nid)
                    self.event_bus.notes_updated.emit(self.current_course_id)
                    self.event_bus.courses_updated.emit()
                    self.event_bus.status_message.emit(
                        f"Unlinked '{item.note.title}' from this course (preserved in Note Browser).",
                        4000,
                    )
            elif chosen == del_act:
                self.scene.clearSelection()
                item.setSelected(True)
                self._on_bulk_delete()
        else:
            scene_pt = self.canvas.mapToScene(pos)
            new_act = menu.addAction("➕ Create Note Here...")
            fit_act = menu.addAction("🎯 Fit View")
            menu.addSeparator()
            layout_act = menu.addAction("⚠️ Auto-Layout DAG...")
            chosen = menu.exec(self.canvas.viewport().mapToGlobal(pos))
            if chosen == new_act:
                self.create_note_at((scene_pt.x(), scene_pt.y()))
            elif chosen == fit_act:
                self._on_fit_view()
            elif chosen == layout_act:
                self._on_auto_layout()
