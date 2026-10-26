from __future__ import annotations

import re
from typing import Any, Callable

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QInputDialog,
    QLayout,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from morphism_srs.theming.delegates import set_widget_props


class FlowLayout(QLayout):
    """Standard Qt FlowLayout that wraps toolbar buttons into multiple rows gracefully."""

    def __init__(self, parent: QWidget | None = None, margin: int = 0, spacing: int = 4) -> None:
        super().__init__(parent)
        if parent is not None:
            self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)
        self.itemList: list[Any] = []

    def __del__(self) -> None:
        item = self.takeAt(0)
        while item:
            item = self.takeAt(0)

    def addItem(self, item: Any) -> None:
        self.itemList.append(item)

    def count(self) -> int:
        return len(self.itemList)

    def itemAt(self, index: int) -> Any:
        if 0 <= index < len(self.itemList):
            return self.itemList[index]
        return None

    def takeAt(self, index: int) -> Any:
        if 0 <= index < len(self.itemList):
            return self.itemList.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self.doLayout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self.doLayout(rect, False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self.itemList:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def doLayout(self, rect: QRect, testOnly: bool) -> int:
        x = rect.x()
        y = rect.y()
        lineHeight = 0
        space = self.spacing()
        for item in self.itemList:
            nextX = x + item.sizeHint().width() + space
            if nextX - space > rect.right() and lineHeight > 0:
                x = rect.x()
                y = y + lineHeight + space
                nextX = x + item.sizeHint().width() + space
                lineHeight = 0
            if not testOnly:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
            x = nextX
            lineHeight = max(lineHeight, item.sizeHint().height())
        return y + lineHeight - rect.y()


def strip_html_for_button(html_lbl: str) -> str:
    txt = html_lbl.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    return re.sub(r"<[^>]+>", "", txt).strip() or html_lbl


class HtmlEditorToolbar(QWidget):
    """Flow-wrapped toolbar for inserting HTML/LaTeX snippets from editor_buttons.json into a QPlainTextEdit."""

    def __init__(
        self,
        get_active_editor: Callable[[], QPlainTextEdit | None],
        custom_buttons: list[dict[str, Any]] | None = None,
        on_insert_media: Callable[[], None] | None = None,
        bind_shortcuts_to: QWidget | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.get_active_editor = get_active_editor
        self.on_insert_media = on_insert_media
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

        layout = FlowLayout(self, margin=0, spacing=4)

        buttons_cfg = custom_buttons or [
            {"label": "B", "type": "interval", "left": "<b>", "right": "</b>", "default_text": "bold"},
            {"label": "I", "type": "interval", "left": "<i>", "right": "</i>", "default_text": "italic"},
            {"label": "U", "type": "interval", "left": "<u>", "right": "</u>", "default_text": "underline"},
            {"label": "<br>", "type": "single", "content": "<br>\n"},
            {"label": "<ul>", "type": "interval", "left": "<ul>\n  <li>", "right": "</li>\n</ul>", "default_text": "item"},
            {"label": "<li>", "type": "interval", "left": "<li>", "right": "</li>", "default_text": "item"},
            {"label": "ℝ", "type": "interval", "left": "\\mathbb{", "right": "}", "default_text": "R"},
            {"label": "𝔅", "type": "interval", "left": "\\mathfrak{", "right": "}", "default_text": "B"},
        ]

        for b_cfg in buttons_cfg:
            raw_lbl = str(b_cfg.get("label", "Snippet"))
            clean_lbl = strip_html_for_button(raw_lbl)
            btn = QPushButton(clean_lbl, self)
            btn.setToolTip(str(b_cfg.get("tooltip", clean_lbl)))
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            set_widget_props(btn, variant="ghost")
            btn.setFixedHeight(26)

            b_type = b_cfg.get("type", "interval")
            if b_type == "interval":
                left = str(b_cfg.get("left", b_cfg.get("prefix", "")))
                right = str(b_cfg.get("right", b_cfg.get("suffix", "")))
                default_txt = str(b_cfg.get("default_text", ""))
                cb = lambda _=False, l=left, r=right, d=default_txt: self.wrap_selection(l, r, d)
            elif b_type == "single":
                content = str(b_cfg.get("content", ""))
                cb = lambda _=False, c=content: self.insert_single(c)
            elif b_type == "action":
                act = str(b_cfg.get("action", ""))
                cb = lambda _=False, a=act: self.trigger_action(a)
            else:
                left = str(b_cfg.get("prefix", ""))
                right = str(b_cfg.get("suffix", ""))
                cb = lambda _=False, l=left, r=right: self.wrap_selection(l, r, "")

            btn.clicked.connect(cb)
            layout.addWidget(btn)

            shortcut_str = b_cfg.get("shortcut")
            if shortcut_str and bind_shortcuts_to is not None:
                sc = QShortcut(QKeySequence(str(shortcut_str)), bind_shortcuts_to)
                sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
                sc.activated.connect(cb)

    def wrap_selection(self, prefix: str, suffix: str, default_text: str = "") -> None:
        editor = self.get_active_editor()
        if editor is None:
            return
        cursor = editor.textCursor()
        if cursor.hasSelection():
            selected = cursor.selectedText().replace("\u2029", "\n")
            cursor.insertText(f"{prefix}{selected}{suffix}")
        else:
            cursor.insertText(f"{prefix}{default_text}{suffix}")
        editor.setFocus()

    def insert_single(self, content: str) -> None:
        editor = self.get_active_editor()
        if editor is None:
            return
        editor.textCursor().insertText(content)
        editor.setFocus()

    def trigger_action(self, action_name: str) -> None:
        editor = self.get_active_editor()
        if editor is None:
            return
        if action_name == "prompt_image":
            if self.on_insert_media is not None:
                self.on_insert_media()
            else:
                url, ok = QInputDialog.getText(self, "Insert Image", "Image URL or filename:")
                if ok and url.strip():
                    editor.textCursor().insertText(f'<img src="{url.strip()}" style="max-width: 100%;">')
        elif action_name == "prompt_table":
            rows, ok1 = QInputDialog.getInt(self, "Insert HTML Table", "Rows:", 2, 1, 20)
            if not ok1:
                return
            cols, ok2 = QInputDialog.getInt(self, "Insert HTML Table", "Columns:", 2, 1, 10)
            if not ok2:
                return
            html = ['<table border="1" style="border-collapse: collapse; width: 100%;">']
            for r in range(rows):
                html.append("  <tr>")
                for c in range(cols):
                    tag = "th" if r == 0 else "td"
                    html.append(f'    <{tag} style="padding: 6px;">Cell</{tag}>')
                html.append("  </tr>")
            html.append("</table>\n")
            editor.textCursor().insertText("\n".join(html))
        editor.setFocus()
