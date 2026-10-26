from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QWidget


def set_widget_props(widget: QWidget, **props: Any) -> None:
    """Sets dynamic Qt properties on a widget and unpolishes/polishes its style."""
    for key, val in props.items():
        widget.setProperty(key, val)
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)
    widget.update()
