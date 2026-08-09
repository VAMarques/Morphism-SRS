import math
from typing import List, Dict, Optional, Set
from PySide6.QtWidgets import (QGraphicsView, QGraphicsScene, QGraphicsItem, 
                               QGraphicsRectItem, QGraphicsPathItem, QMenu)
from PySide6.QtCore import Qt, Signal, QObject, QPointF, QRectF
from PySide6.QtGui import (QBrush, QColor, QPen, QPainterPath, QPolygonF, 
                           QLinearGradient, QFont, QPainter)
from models import NoteNode, NoteEdge
from styles import DARK_THEME_QSS

class GraphSignals(QObject):
    """Signals for graph interactions and context menu actions."""
    note_selected_for_review = Signal(object)   # NoteNode
    note_clicked = Signal(object)               # NoteNode
    node_moved = Signal(object)                 # NoteNode
    note_edit_requested = Signal(object)        # NoteNode
    note_info_requested = Signal(object)        # NoteNode
    note_add_prereq_requested = Signal(object)   # NoteNode (target)
    note_delete_prereqs_requested = Signal(object)# NoteNode
    note_reschedule_requested = Signal(object)   # NoteNode
    note_force_review_requested = Signal(object) # NoteNode
    note_delete_requested = Signal(object)      # NoteNode



    prereq_edge_created = Signal(str, str)      # source_id, target_id

class NoteNodeItem(QGraphicsRectItem):
    """Custom graphical item for Note nodes on the canvas."""
    
    WIDTH = 180
    HEIGHT = 80
    CORNER_RADIUS = 12

    def __init__(self, note: NoteNode, signals: GraphSignals):
        super().__init__(0, 0, self.WIDTH, self.HEIGHT)
        self.note = note
        self.signals = signals
        self.edges: List['NoteEdgeItem'] = []

        self.setPos(note.x, note.y)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)

        self._setup_appearance()

    def _setup_appearance(self):
        self.update_status_colors()

    def update_status_colors(self, scheduler_manager=None):
        """Update node gradient & border based on due cards count and joint retention."""
        if self.note.is_serial_sequence():
            joint_r = self.note.get_joint_retention(scheduler_manager)
            ret_percent = int(joint_r * 100)
            is_due = self.note.is_due(scheduler_manager)
            total = self.note.total_count()

            if is_due:
                bg_start = QColor("#991b1b")
                bg_end = QColor("#450a0a")
                border_color = QColor("#fca5a5")
                badge_text = f"🔥 Serial {total}s | P={ret_percent}%"
            else:
                bg_start = QColor("#1e1b4b")
                bg_end = QColor("#0f172a")
                border_color = QColor("#818cf8")
                badge_text = f"🔗 Serial {total}s | P={ret_percent}%"
        else:
            due_count = self.note.due_count(scheduler_manager)
            total = self.note.total_count()

            if self.note.is_due(scheduler_manager):
                bg_start = QColor("#ef4444")
                bg_end = QColor("#991b1b")
                border_color = QColor("#fca5a5")
                badge_text = f"🔥 {due_count} Due"
            elif total > 0:
                bg_start = QColor("#1e293b")
                bg_end = QColor("#0f172a")
                border_color = QColor("#10b981")
                badge_text = f"✓ {total} Cards"
            else:
                bg_start = QColor("#334155")
                bg_end = QColor("#1e293b")
                border_color = QColor("#64748b")
                badge_text = "0 Cards"

        self.border_pen = QPen(border_color, 2)
        self.bg_gradient = QLinearGradient(0, 0, self.WIDTH, self.HEIGHT)
        self.bg_gradient.setColorAt(0.0, bg_start)
        self.bg_gradient.setColorAt(1.0, bg_end)

        self.badge_text = badge_text
        self.update()

    def add_edge(self, edge_item: 'NoteEdgeItem'):
        self.edges.append(edge_item)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.note.x = self.pos().x()
            self.note.y = self.pos().y()
            for edge in self.edges:
                edge.update_position()
            self.signals.node_moved.emit(self.note)
        return super().itemChange(change, value)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)

        path = QPainterPath()
        path.addRoundedRect(0, 0, self.WIDTH, self.HEIGHT, self.CORNER_RADIUS, self.CORNER_RADIUS)

        if self.isSelected():
            painter.setPen(QPen(QColor("#38bdf8"), 3, Qt.DashLine))
        else:
            painter.setPen(self.border_pen)

        painter.setBrush(self.bg_gradient)
        painter.drawPath(path)

        # Title Text
        painter.setPen(QColor("#f8fafc"))
        font_title = QFont("Segoe UI", 11, QFont.Bold)
        painter.setFont(font_title)
        rect_title = QRectF(12, 10, self.WIDTH - 24, 30)
        title_text = painter.fontMetrics().elidedText(self.note.title, Qt.ElideRight, int(rect_title.width()))
        painter.drawText(rect_title, Qt.AlignLeft | Qt.AlignVCenter, title_text)

        # Status Badge Pill
        font_badge = QFont("Segoe UI", 9)
        painter.setFont(font_badge)
        painter.setPen(QColor("#94a3b8"))
        rect_badge = QRectF(12, 45, self.WIDTH - 24, 24)
        painter.drawText(rect_badge, Qt.AlignLeft | Qt.AlignVCenter, self.badge_text)

    def mousePressEvent(self, event):
        self.signals.note_clicked.emit(self.note)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        """Double click node -> trigger review window."""
        super().mouseDoubleClickEvent(event)
        self.signals.note_selected_for_review.emit(self.note)


    def contextMenuEvent(self, event):
        """Right-click context menu: Edit, Info, Add prerequisites, Delete."""
        menu = QMenu()
        menu.setStyleSheet(DARK_THEME_QSS)

        act_edit = menu.addAction("✏️ Edit Note")
        act_info = menu.addAction("📈 Info / Retrievability Plot")
        act_prereq = menu.addAction("🔗 Add Prerequisites")
        act_delete_prereqs = menu.addAction("✂️ Delete Prerequisites")
        act_reschedule = menu.addAction("🔄 Reschedule Note FSRS State")
        act_force_review = menu.addAction("▶️ Review All Cards / Steps (Force Review)")
        menu.addSeparator()
        act_delete = menu.addAction("🗑 Delete Note")

        action = menu.exec(event.screenPos())
        if action == act_edit:
            self.signals.note_edit_requested.emit(self.note)
        elif action == act_info:
            self.signals.note_info_requested.emit(self.note)
        elif action == act_prereq:
            self.signals.note_add_prereq_requested.emit(self.note)
        elif action == act_delete_prereqs:
            self.signals.note_delete_prereqs_requested.emit(self.note)
        elif action == act_reschedule:
            self.signals.note_reschedule_requested.emit(self.note)
        elif action == act_force_review:
            self.signals.note_force_review_requested.emit(self.note)
        elif action == act_delete:
            self.signals.note_delete_requested.emit(self.note)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.scene():
            views = self.scene().views()
            if views and getattr(views[0], 'is_snapping_enabled', False):
                pos = value
                grid_x = getattr(views[0], 'GRID_X', 300)
                grid_y = getattr(views[0], 'GRID_Y', 130)
                snapped_x = round(pos.x() / grid_x) * grid_x
                snapped_y = round(pos.y() / grid_y) * grid_y
                return QPointF(snapped_x, snapped_y)

        if change == QGraphicsItem.ItemPositionHasChanged:
            self.note.x = self.pos().x()
            self.note.y = self.pos().y()
            for edge_item in self.edges:
                edge_item.update_position()

        return super().itemChange(change, value)





class NoteEdgeItem(QGraphicsPathItem):
    """Directed connection arrow between two Note nodes."""

    def __init__(self, source_item: NoteNodeItem, target_item: NoteNodeItem, edge_model: NoteEdge):
        super().__init__()
        self.source_item = source_item
        self.target_item = target_item
        self.edge_model = edge_model

        self.source_item.add_edge(self)
        self.target_item.add_edge(self)

        self.setPen(QPen(QColor("#818cf8"), 2.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        self.setBrush(QBrush(QColor("#818cf8")))
        self.setZValue(5)
        self.update_position()

    @staticmethod
    def _get_border_intersection(rect_pos: QPointF, width: float, height: float, target_point: QPointF) -> QPointF:
        cx = rect_pos.x() + width / 2.0
        cy = rect_pos.y() + height / 2.0
        dx = target_point.x() - cx
        dy = target_point.y() - cy
        if abs(dx) < 1e-6 and abs(dy) < 1e-6:
            return QPointF(cx, cy)
        w2 = width / 2.0 + 4
        h2 = height / 2.0 + 4
        scale_x = w2 / abs(dx) if dx != 0 else 1e9
        scale_y = h2 / abs(dy) if dy != 0 else 1e9
        scale = min(scale_x, scale_y)
        return QPointF(cx + dx * scale, cy + dy * scale)

    def update_position(self):
        src_center = self.source_item.pos() + QPointF(self.source_item.WIDTH / 2, self.source_item.HEIGHT / 2)
        tgt_center = self.target_item.pos() + QPointF(self.target_item.WIDTH / 2, self.target_item.HEIGHT / 2)

        start_point = self._get_border_intersection(self.source_item.pos(), self.source_item.WIDTH, self.source_item.HEIGHT, tgt_center)
        end_point = self._get_border_intersection(self.target_item.pos(), self.target_item.WIDTH, self.target_item.HEIGHT, src_center)

        path = QPainterPath()
        path.moveTo(start_point)

        dx = end_point.x() - start_point.x()
        dy = end_point.y() - start_point.y()

        ctrl1 = QPointF(start_point.x() + dx * 0.4, start_point.y())
        ctrl2 = QPointF(end_point.x() - dx * 0.4, end_point.y())

        path.cubicTo(ctrl1, ctrl2, end_point)

        angle = math.atan2(dy, dx)
        arrow_size = 14
        arrow_p1 = end_point - QPointF(math.cos(angle - math.pi / 6) * arrow_size,
                                       math.sin(angle - math.pi / 6) * arrow_size)
        arrow_p2 = end_point - QPointF(math.cos(angle + math.pi / 6) * arrow_size,
                                       math.sin(angle + math.pi / 6) * arrow_size)

        arrow_head = QPolygonF([end_point, arrow_p1, arrow_p2])
        path.addPolygon(arrow_head)

        self.setPath(path)


class GraphWidget(QGraphicsView):
    """Infinite canvas graphics view supporting drag, zoom, context menus, and prerequisite linking."""

    GRID_X = 300
    GRID_Y = 130

    def __init__(self, notes: List[NoteNode], edges: List[NoteEdge], scheduler_manager=None):
        super().__init__()
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.scene.setSceneRect(-25000, -25000, 50000, 50000)

        self.scheduler_manager = scheduler_manager
        self.signals = GraphSignals()
        self.node_items: Dict[str, NoteNodeItem] = {}
        self.edge_items: List[NoteEdgeItem] = []
        self.is_snapping_enabled = False

        # Interactive Prerequisite Linking Mode State
        self.prereq_target_node: Optional[NoteNode] = None
        self.temp_prereq_path_item: Optional[QGraphicsPathItem] = None

        self._setup_canvas()
        self.signals.note_add_prereq_requested.connect(self.start_prereq_mode)
        self.load_graph(notes, edges)

    def set_snapping_enabled(self, enabled: bool):
        self.is_snapping_enabled = enabled

    def _adjust_scene_rect(self):
        """Ensure sceneRect dynamically encompasses all nodes plus a generous padding margin."""
        items_rect = self.scene.itemsBoundingRect()
        margin = 6000
        x = min(-25000.0, items_rect.x() - margin)
        y = min(-25000.0, items_rect.y() - margin)
        w = max(50000.0, items_rect.width() + 2 * margin)
        h = max(50000.0, items_rect.height() + 2 * margin)
        self.scene.setSceneRect(x, y, w, h)

    def _setup_canvas(self):
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("background-color: #0b0f19; border: none;")
        self.setMouseTracking(True)

    def load_graph(self, notes: List[NoteNode], edges: List[NoteEdge]):
        """Clear and load nodes and edges into scene."""
        self.stop_prereq_mode()
        self.scene.clear()
        self.node_items.clear()
        self.edge_items.clear()

        # Add Nodes
        for note in notes:
            node_item = NoteNodeItem(note, self.signals)
            node_item.update_status_colors(self.scheduler_manager)
            self.scene.addItem(node_item)
            self.node_items[note.note_id] = node_item

        # Add Edges
        for edge in edges:
            src = self.node_items.get(edge.source_id)
            tgt = self.node_items.get(edge.target_id)
            if src and tgt:
                edge_item = NoteEdgeItem(src, tgt, edge)
                self.scene.addItem(edge_item)
                self.edge_items.append(edge_item)

        self._adjust_scene_rect()


    def refresh_nodes(self):
        """Update node status appearance after review."""
        for item in self.node_items.values():
            item.update_status_colors(self.scheduler_manager)

    def start_prereq_mode(self, target_note: NoteNode):
        """Enter interactive prerequisite linking mode for a target node."""
        self.prereq_target_node = target_note
        if self.temp_prereq_path_item is None:
            self.temp_prereq_path_item = QGraphicsPathItem()
            pen = QPen(QColor("#f59e0b"), 3, Qt.DashDotLine)
            self.temp_prereq_path_item.setPen(pen)
            self.temp_prereq_path_item.setBrush(QBrush(QColor("#f59e0b")))
            self.temp_prereq_path_item.setZValue(15)
            self.scene.addItem(self.temp_prereq_path_item)
        self.setCursor(Qt.CrossCursor)

    def stop_prereq_mode(self):
        """Exit interactive prerequisite mode."""
        self.prereq_target_node = None
        if self.temp_prereq_path_item is not None:
            self.scene.removeItem(self.temp_prereq_path_item)
            self.temp_prereq_path_item = None
        self.setCursor(Qt.ArrowCursor)

    def mouseMoveEvent(self, event):
        if self.prereq_target_node and self.temp_prereq_path_item:
            target_item = self.node_items.get(self.prereq_target_node.note_id)
            if target_item:
                tgt_center = target_item.pos() + QPointF(target_item.WIDTH / 2, target_item.HEIGHT / 2)
                cursor_scene_pos = self.mapToScene(event.pos())

                path = QPainterPath()
                path.moveTo(cursor_scene_pos)
                path.lineTo(tgt_center)

                # Draw arrowhead pointing to target_center
                dx = tgt_center.x() - cursor_scene_pos.x()
                dy = tgt_center.y() - cursor_scene_pos.y()
                angle = math.atan2(dy, dx)
                arrow_size = 12
                arrow_p1 = tgt_center - QPointF(math.cos(angle - math.pi / 6) * arrow_size,
                                                   math.sin(angle - math.pi / 6) * arrow_size)
                arrow_p2 = tgt_center - QPointF(math.cos(angle + math.pi / 6) * arrow_size,
                                                   math.sin(angle + math.pi / 6) * arrow_size)
                arrow_head = QPolygonF([tgt_center, arrow_p1, arrow_p2])
                path.addPolygon(arrow_head)

                self.temp_prereq_path_item.setPath(path)

        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if self.prereq_target_node:
            scene_pos = self.mapToScene(event.pos())
            items = self.scene.items(scene_pos)
            clicked_node_item = None

            for it in items:
                curr = it
                while curr and not isinstance(curr, NoteNodeItem):
                    curr = curr.parentItem()
                if isinstance(curr, NoteNodeItem):
                    clicked_node_item = curr
                    break

            if clicked_node_item:
                clicked_note = clicked_node_item.note
                if clicked_note.note_id != self.prereq_target_node.note_id:
                    self.signals.prereq_edge_created.emit(clicked_note.note_id, self.prereq_target_node.note_id)
                self.stop_prereq_mode()
            else:
                self.stop_prereq_mode()
            return

        super().mousePressEvent(event)


    def wheelEvent(self, event):
        zoom_factor = 1.15
        if event.angleDelta().y() > 0:
            self.scale(zoom_factor, zoom_factor)
        else:
            self.scale(1 / zoom_factor, 1 / zoom_factor)

    def auto_arrange(self):
        """
        Topological Hierarchy Tree Layout:
        Arranges prerequisite root nodes on the left and dependent nodes in successive columns to the right.
        """
        nodes = list(self.node_items.values())
        if not nodes:
            return

        # Build adjacency & in-degree maps
        in_degree: Dict[str, int] = {n.note.note_id: 0 for n in nodes}
        adj: Dict[str, List[str]] = {n.note.note_id: [] for n in nodes}

        for edge_item in self.edge_items:
            src_id = edge_item.edge_model.source_id
            tgt_id = edge_item.edge_model.target_id
            if src_id in in_degree and tgt_id in in_degree:
                adj[src_id].append(tgt_id)
                in_degree[tgt_id] += 1

        # Calculate depth levels (Topological Layering)
        level: Dict[str, int] = {n.note.note_id: 0 for n in nodes}
        queue = [nid for nid, deg in in_degree.items() if deg == 0]

        visited: Set[str] = set(queue)
        while queue:
            curr = queue.pop(0)
            for neighbor in adj[curr]:
                level[neighbor] = max(level[neighbor], level[curr] + 1)
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0 or neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)

        # Group nodes by depth level
        levels_map: Dict[int, List[NoteNodeItem]] = {}
        for node_item in nodes:
            lvl = level[node_item.note.note_id]
            levels_map.setdefault(lvl, []).append(node_item)

        # Position nodes in clean columns
        x_spacing = 300
        y_spacing = 130

        for lvl in sorted(levels_map.keys()):
            column_nodes = levels_map[lvl]
            total_height = (len(column_nodes) - 1) * y_spacing
            start_y = -total_height / 2.0
            x_pos = (lvl - (len(levels_map) - 1) / 2.0) * x_spacing

            for idx, node_item in enumerate(column_nodes):
                y_pos = start_y + idx * y_spacing
                node_item.setPos(x_pos, y_pos)

        for edge in self.edge_items:
            edge.update_position()

        self._adjust_scene_rect()

