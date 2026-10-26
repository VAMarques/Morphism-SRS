from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFrame, QScrollArea, QSplitter, QWidget


def apply_relative_geometry(
    widget: QWidget,
    width_ratio: float = 0.85,
    height_ratio: float = 0.85,
    min_width: int = 860,
    min_height: int = 560,
    center: bool = True,
) -> None:
    """
    Applies screen-relative geometry using QScreen.availableGeometry() so windows
    and dialogs fit comfortably on 720p (1280x720 / 1366x768) laptop displays as well as 4K screens.
    """
    screen = widget.screen() or QGuiApplication.primaryScreen()
    if screen is None:
        widget.setMinimumSize(min_width, min_height)
        widget.resize(min_width, min_height)
        return

    avail = screen.availableGeometry()
    eff_min_w = min(min_width, int(avail.width() * 0.96))
    eff_min_h = min(min_height, int(avail.height() * 0.94))
    widget.setMinimumSize(eff_min_w, eff_min_h)

    target_w = max(eff_min_w, min(int(avail.width() * width_ratio), int(avail.width() * 0.96)))
    target_h = max(eff_min_h, min(int(avail.height() * height_ratio), int(avail.height() * 0.94)))
    widget.resize(target_w, target_h)

    if center:
        x = avail.x() + (avail.width() - target_w) // 2
        y = avail.y() + (avail.height() - target_h) // 2
        widget.move(max(avail.x(), x), max(avail.y(), y))


def configure_splitter(
    splitter: QSplitter,
    min_sizes: list[int] | None = None,
    initial_sizes: list[int] | None = None,
) -> None:
    """
    Prevents any QSplitter child pane from collapsing to size 0 and enforces explicit
    minimum widths/heights on each child widget.
    """
    splitter.setChildrenCollapsible(False)
    splitter.setHandleWidth(6)
    is_horiz = splitter.orientation() == Qt.Orientation.Horizontal
    count = splitter.count()
    for i in range(count):
        child = splitter.widget(i)
        if child is None:
            continue
        splitter.setCollapsible(i, False)
        min_px = min_sizes[i] if (min_sizes and i < len(min_sizes)) else (180 if is_horiz else 110)
        if is_horiz:
            child.setMinimumWidth(max(child.minimumWidth(), min_px))
        else:
            child.setMinimumHeight(max(child.minimumHeight(), min_px))

    if initial_sizes and len(initial_sizes) == count:
        splitter.setSizes(initial_sizes)


def wrap_in_scroll_area(
    content_widget: QWidget,
    parent: QWidget | None = None,
    min_width: int = 580,
    min_height: int = 380,
) -> QScrollArea:
    """
    Wraps a view or dialog content widget inside a frameless QScrollArea(widgetResizable=True)
    with a guaranteed minimum content size so scrollbars appear automatically instead of squishing subpanes to 0.
    """
    content_widget.setMinimumSize(
        max(content_widget.minimumWidth(), min_width),
        max(content_widget.minimumHeight(), min_height),
    )
    scroll = QScrollArea(parent)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setWidget(content_widget)
    return scroll
