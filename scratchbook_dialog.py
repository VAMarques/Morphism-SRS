import os
import json
import re
import html
from typing import List, Optional

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
                               QLabel, QLineEdit, QTextEdit, QListWidget, QListWidgetItem,
                               QGroupBox, QMessageBox, QWidget, QSplitter, QInputDialog)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtCore import Qt, QUrl, QTimer
from PySide6.QtGui import QFont, QKeySequence, QShortcut

from node_editor_dialog import (FlowLayout, load_editor_buttons_config, 
                                load_mathjax_config_json, prompt_insert_image, prompt_insert_table)

SCRATCHBOOK_DIR = "scratchbook"
ASSETS_DIR = os.path.abspath("assets").replace("\\", "/")


def build_scratchbook_html_template(content: str = "") -> str:
    """Build MathJax HTML page template for scratchbook live preview matching note editor."""
    mathjax_cfg = load_mathjax_config_json()
    cfg_json = json.dumps(mathjax_cfg)
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{
            background-color: #0b0f19;
            color: #f8fafc;
            font-family: -apple-system, "BlinkMacSystemFont", "SF Pro Text", "Helvetica Neue", "Segoe UI", Roboto, "Ubuntu", "DejaVu Sans", sans-serif;
            padding: 16px;
            margin: 0;
            line-height: 1.6;
        }}
        img {{
            max-width: 100%;
            border-radius: 8px;
        }}
        table {{
            border-collapse: collapse;
            width: 100%;
            margin: 10px 0;
            background: rgba(15, 23, 42, 0.6);
        }}
        th, td {{
            border: 1px solid #334155;
            padding: 8px 12px;
            text-align: left;
        }}
        th {{
            background-color: #1e293b;
            color: #38bdf8;
        }}
        code {{ background: #0f172a; color: #f43f5e; padding: 2px 6px; border-radius: 4px; font-family: monospace; }}
        pre {{ background: #0f172a; padding: 12px; border-radius: 8px; overflow-x: auto; border: 1px solid #334155; }}
    </style>

    <!-- MathJax 3 Offline Configuration matching Note Editor -->
    <script>
        window.MathJax = {{
            tex: {cfg_json},
            svg: {{
                fontCache: 'local'
            }},
            options: {{
                skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre']
            }}
        }};
    </script>

    <!-- Load Local Self-Contained MathJax 3 SVG Bundle for Vector Typesetting -->
    <script src="tex-svg.js"></script>

    <script>
        window.updatePreview = function(htmlContent) {{
            let container = document.getElementById('content');
            if (!container) return;
            container.innerHTML = htmlContent;
            if (window.MathJax && window.MathJax.typesetPromise) {{
                MathJax.typesetPromise([container]).catch(function(err) {{
                    console.log(err);
                }});
            }}
        }};
    </script>
</head>
<body>
    <div id="content">{content}</div>
</body>
</html>"""



def sanitize_page_filename(name: str) -> str:
    """Sanitize page name for OS filename safety."""
    return "".join(c for c in name if c.isalnum() or c in (' ', '_', '-')).strip() or "Untitled"


class ScratchbookDialog(QDialog):
    """Standalone resizable & maximizable Scratchbook Window with multi-page .txt storage & live MathJax preview."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_page_name: Optional[str] = None
        self.is_page_loaded = False

        self.setWindowTitle("✏️ Scratchbook")
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint | Qt.WindowMinimizeButtonHint)
        self.setWindowModality(Qt.NonModal)
        self.setMinimumSize(840, 560)
        self.resize(1120, 760)


        os.makedirs(SCRATCHBOOK_DIR, exist_ok=True)

        self._setup_ui()
        self._load_pages_list()

        # Preview update timer for smooth debounced typing
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(300)
        self.preview_timer.timeout.connect(self._sync_current_page_to_preview_and_disk)

    def _setup_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)

        splitter = QSplitter(Qt.Horizontal)

        # ----------------------------------------------------------------------
        # Left Sidebar: Page List & Page Management Buttons
        # ----------------------------------------------------------------------
        sidebar_widget = QWidget()
        sidebar_layout = QVBoxLayout(sidebar_widget)
        sidebar_layout.setContentsMargins(0, 0, 6, 0)
        sidebar_layout.setSpacing(8)

        lbl_pages = QLabel("📖 Scratch Pages")
        lbl_pages.setStyleSheet("font-size: 15px; font-weight: bold; color: #38bdf8;")
        sidebar_layout.addWidget(lbl_pages)

        self.list_pages = QListWidget()
        self.list_pages.setStyleSheet(
            "QListWidget { background-color: #0f172a; border: 1px solid #334155; border-radius: 8px; font-size: 13px; padding: 4px; }"
            "QListWidget::item { padding: 8px; border-radius: 4px; }"
            "QListWidget::item:selected { background-color: #0284c7; color: white; font-weight: bold; }"
        )
        self.list_pages.currentItemChanged.connect(self._on_page_selection_changed)
        sidebar_layout.addWidget(self.list_pages, stretch=1)

        # Sidebar Buttons
        btn_layout = QHBoxLayout()
        self.btn_add_page = QPushButton("+ New")
        self.btn_add_page.setStyleSheet("background-color: #10b981; color: white; font-weight: bold; padding: 6px 10px; border-radius: 6px;")
        self.btn_add_page.clicked.connect(self._add_new_page)

        self.btn_rename_page = QPushButton("✏️ Rename")
        self.btn_rename_page.setStyleSheet("background-color: #334155; color: #f8fafc; font-weight: bold; padding: 6px 10px; border-radius: 6px;")
        self.btn_rename_page.clicked.connect(self._rename_current_page)

        self.btn_delete_page = QPushButton("🗑️ Delete")
        self.btn_delete_page.setStyleSheet("background-color: #dc2626; color: white; font-weight: bold; padding: 6px 10px; border-radius: 6px;")
        self.btn_delete_page.clicked.connect(self._delete_current_page)

        btn_layout.addWidget(self.btn_add_page)
        btn_layout.addWidget(self.btn_rename_page)
        btn_layout.addWidget(self.btn_delete_page)
        sidebar_layout.addLayout(btn_layout)

        splitter.addWidget(sidebar_widget)

        # ----------------------------------------------------------------------
        # Right Side: Editor & Live Preview Panel
        # ----------------------------------------------------------------------
        editor_panel = QWidget()
        editor_layout = QVBoxLayout(editor_panel)
        editor_layout.setContentsMargins(6, 0, 0, 0)
        editor_layout.setSpacing(8)

        # Page Header Banner
        self.lbl_active_page_title = QLabel("Select or Create a Page")
        self.lbl_active_page_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #f8fafc;")
        editor_layout.addWidget(self.lbl_active_page_title)

        # Formatting Toolbar Container (FlowLayout using assets/editor_buttons.json)
        toolbar_container = QWidget()
        toolbar_container.setStyleSheet("background-color: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 4px;")
        toolbar_container_layout = QVBoxLayout(toolbar_container)
        toolbar_container_layout.setContentsMargins(6, 6, 6, 6)

        self.formatting_toolbar_layout = self._create_formatting_toolbar()
        toolbar_container_layout.addLayout(self.formatting_toolbar_layout)
        editor_layout.addWidget(toolbar_container)

        # Split Editor (TextEdit + Live MathJax Preview)
        editor_splitter = QSplitter(Qt.Horizontal)

        # Text Editor
        self.txt_editor = QTextEdit()
        self.txt_editor.setPlaceholderText("Write HTML and LaTeX math ($...$, $$...$$) here...")
        self.txt_editor.setStyleSheet(
            "QTextEdit { background-color: #0f172a; border: 1px solid #334155; border-radius: 8px; color: #f8fafc; font-family: 'Consolas', 'Liberation Mono', 'DejaVu Sans Mono', monospace; font-size: 13px; padding: 10px; }"
        )
        self.txt_editor.textChanged.connect(self._on_text_changed)
        editor_splitter.addWidget(self.txt_editor)

        # WebEngine Live Preview
        self.browser_preview = QWebEngineView()
        self.browser_preview.setHtml(build_scratchbook_html_template(""), QUrl.fromLocalFile(ASSETS_DIR + "/"))
        self.browser_preview.loadFinished.connect(self._on_preview_loaded)
        editor_splitter.addWidget(self.browser_preview)

        editor_splitter.setSizes([500, 500])
        editor_layout.addWidget(editor_splitter, stretch=1)

        splitter.addWidget(editor_panel)
        splitter.setSizes([260, 860])

        main_layout.addWidget(splitter)

    def _create_formatting_toolbar(self) -> FlowLayout:
        """Create rich HTML formatting toolbar with dynamic FlowLayout wrapping based on assets/editor_buttons.json."""
        layout = FlowLayout(spacing=6)

        buttons_config = load_editor_buttons_config()
        for btn_info in buttons_config:
            label_text = btn_info.get("label", "Button")
            tooltip_text = btn_info.get("tooltip", "")
            btn_type = btn_info.get("type", "single")

            btn = QPushButton()
            self._configure_button_rich_text(btn, label_text)
            if tooltip_text:
                btn.setToolTip(tooltip_text)

            if btn_type == "interval":
                left = btn_info.get("left", "")
                right = btn_info.get("right", "")
                default_text = btn_info.get("default_text", "")
                btn.clicked.connect(lambda _, l=left, r=right, d=default_text: self._apply_interval(l, r, d))
            elif btn_type == "single":
                content = btn_info.get("content", "")
                btn.clicked.connect(lambda _, c=content: self.txt_editor.textCursor().insertText(c))
            elif btn_type == "action":
                act_name = btn_info.get("action", "")
                if act_name == "prompt_image":
                    btn.clicked.connect(lambda: prompt_insert_image(self.txt_editor, self))
                elif act_name == "prompt_table":
                    btn.clicked.connect(lambda: prompt_insert_table(self.txt_editor))

            layout.addWidget(btn)

            # Register shortcut key if present
            shortcut_key = btn_info.get("shortcut", "")
            if shortcut_key:
                sc = QShortcut(QKeySequence(shortcut_key), self)
                sc.setContext(Qt.WindowShortcut)
                sc.activated.connect(lambda info=btn_info: self._trigger_shortcut_action(info))

        return layout

    def _configure_button_rich_text(self, btn: QPushButton, raw_label: str):
        """Parse raw label (unescaping HTML entities) and configure QPushButton styling."""
        label_str = html.unescape(raw_label)
        plain_text = re.sub(r'<[^>]+>', '', label_str)
        btn.setText(plain_text)

        is_bold = "<b>" in label_str or "font-weight: bold" in label_str or "font-weight:bold" in label_str
        is_italic = "<i>" in label_str or "font-style: italic" in label_str or "font-style:italic" in label_str
        is_underline = "<u>" in label_str or "text-decoration: underline" in label_str

        color_match = re.search(r"color=['\"]?([^'\">\s;]+)", label_str)
        text_color = color_match.group(1) if color_match else "#f8fafc"

        font = btn.font()
        font.setBold(is_bold)
        font.setItalic(is_italic)
        font.setUnderline(is_underline)
        btn.setFont(font)

        style = f"font-size: 12px; padding: 4px 10px; min-width: 26px; color: {text_color};"
        if is_bold:
            style += " font-weight: bold;"
        if is_italic:
            style += " font-style: italic;"
        if is_underline:
            style += " text-decoration: underline;"
        btn.setStyleSheet(style)

    def _apply_interval(self, left: str, right: str, default_text: str = ""):
        cursor = self.txt_editor.textCursor()
        selected = cursor.selectedText()
        if selected:
            cursor.insertText(f"{left}{selected}{right}")
        else:
            val = default_text if default_text else "text"
            cursor.insertText(f"{left}{val}{right}")

    def _trigger_shortcut_action(self, btn_info: dict):
        btn_type = btn_info.get("type", "single")
        if btn_type == "interval":
            left = btn_info.get("left", "")
            right = btn_info.get("right", "")
            default_text = btn_info.get("default_text", "")
            self._apply_interval(left, right, default_text)
        elif btn_type == "single":
            content = btn_info.get("content", "")
            self.txt_editor.textCursor().insertText(content)
        elif btn_type == "action":
            act_name = btn_info.get("action", "")
            if act_name == "prompt_image":
                prompt_insert_image(self.txt_editor, self)
            elif act_name == "prompt_table":
                prompt_insert_table(self.txt_editor)

    def _load_pages_list(self):
        """Scan scratchbook/*.txt files and populate the sidebar page list."""
        self.list_pages.blockSignals(True)
        self.list_pages.clear()

        files = [f for f in os.listdir(SCRATCHBOOK_DIR) if f.endswith(".txt")]
        page_names = sorted([os.path.splitext(f)[0] for f in files])

        if not page_names:
            # Create a default initial page if directory is empty
            default_name = "General Notes"
            default_file = os.path.join(SCRATCHBOOK_DIR, f"{default_name}.txt")
            sample_content = (
                "<h2>✏️ Welcome to Scratchbook!</h2>\n"
                "<p>Write notes, formulas, and proofs freely here.</p>\n"
                "<p>Euler's Identity: $e^{{i\\pi}} + 1 = 0$</p>\n"
            )
            with open(default_file, "w", encoding="utf-8") as f:
                f.write(sample_content)
            page_names = [default_name]

        for p_name in page_names:
            item = QListWidgetItem(f"📄 {p_name}")
            item.setData(Qt.UserRole, p_name)
            self.list_pages.addItem(item)

        self.list_pages.blockSignals(False)

        if self.list_pages.count() > 0:
            self.list_pages.setCurrentRow(0)

    def _on_page_selection_changed(self, current: Optional[QListWidgetItem], previous: Optional[QListWidgetItem]):
        """Save previous page content and load newly selected page from disk."""
        if previous:
            prev_name = previous.data(Qt.UserRole)
            self._save_page_to_disk(prev_name, self.txt_editor.toPlainText())

        if not current:
            self.current_page_name = None
            self.lbl_active_page_title.setText("No Page Selected")
            self.txt_editor.setPlainText("")
            return

        page_name = current.data(Qt.UserRole)
        self.current_page_name = page_name
        self.lbl_active_page_title.setText(f"📄 {page_name}")

        file_path = os.path.join(SCRATCHBOOK_DIR, f"{sanitize_page_filename(page_name)}.txt")
        content = ""
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception as e:
                print(f"Error loading page '{page_name}': {e}")

        self.txt_editor.blockSignals(True)
        self.txt_editor.setPlainText(content)
        self.txt_editor.blockSignals(False)

        self._update_preview(content)

    def _on_text_changed(self):
        """Debounce preview update and auto-save to disk."""
        self.preview_timer.start()

    def _sync_current_page_to_preview_and_disk(self):
        if not self.current_page_name:
            return
        content = self.txt_editor.toPlainText()
        self._update_preview(content)
        self._save_page_to_disk(self.current_page_name, content)

    def _save_page_to_disk(self, page_name: str, content: str):
        """Save a page's text content to scratchbook/<Page Name>.txt."""
        if not page_name:
            return
        file_path = os.path.join(SCRATCHBOOK_DIR, f"{sanitize_page_filename(page_name)}.txt")
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            print(f"Error saving scratchbook page '{page_name}': {e}")

    def _on_preview_loaded(self, ok: bool):
        self.is_page_loaded = True
        if self.current_page_name:
            self._update_preview(self.txt_editor.toPlainText())

    def _update_preview(self, content: str):
        if hasattr(self, "is_page_loaded") and self.is_page_loaded:
            js = f"if (typeof updatePreview === 'function') {{ updatePreview({json.dumps(content)}); }}"
            self.browser_preview.page().runJavaScript(js)

    def _add_new_page(self):
        name, ok = QInputDialog.getText(self, "New Page", "Enter name for new scratch page:")
        if ok and name.strip():
            safe_name = sanitize_page_filename(name.strip())
            file_path = os.path.join(SCRATCHBOOK_DIR, f"{safe_name}.txt")
            if os.path.exists(file_path):
                QMessageBox.warning(self, "Page Exists", f"A page named '{safe_name}' already exists.")
                return

            with open(file_path, "w", encoding="utf-8") as f:
                f.write(f"<h2>{html.escape(safe_name)}</h2>\n<p>Start writing your notes...</p>\n")

            item = QListWidgetItem(f"📄 {safe_name}")
            item.setData(Qt.UserRole, safe_name)
            self.list_pages.addItem(item)
            self.list_pages.setCurrentItem(item)

    def _rename_current_page(self):
        if not self.current_page_name or not self.list_pages.currentItem():
            return

        old_name = self.current_page_name
        new_name, ok = QInputDialog.getText(self, "Rename Page", f"Enter new name for '{old_name}':", QLineEdit.Normal, old_name)
        if ok and new_name.strip() and new_name.strip() != old_name:
            safe_new_name = sanitize_page_filename(new_name.strip())
            old_path = os.path.join(SCRATCHBOOK_DIR, f"{sanitize_page_filename(old_name)}.txt")
            new_path = os.path.join(SCRATCHBOOK_DIR, f"{safe_new_name}.txt")

            if os.path.exists(new_path):
                QMessageBox.warning(self, "Page Exists", f"A page named '{safe_new_name}' already exists.")
                return

            # Save current unsaved editor changes first before renaming
            self._save_page_to_disk(old_name, self.txt_editor.toPlainText())

            if os.path.exists(old_path):
                os.rename(old_path, new_path)

            self.current_page_name = safe_new_name
            self.lbl_active_page_title.setText(f"📄 {safe_new_name}")
            curr_item = self.list_pages.currentItem()
            curr_item.setText(f"📄 {safe_new_name}")
            curr_item.setData(Qt.UserRole, safe_new_name)

    def _delete_current_page(self):
        if not self.current_page_name or not self.list_pages.currentItem():
            return

        page_name = self.current_page_name
        reply = QMessageBox.question(
            self, 
            "Delete Page", 
            f"Are you sure you want to delete page '{page_name}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            file_path = os.path.join(SCRATCHBOOK_DIR, f"{sanitize_page_filename(page_name)}.txt")
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception as e:
                    print(f"Error deleting file '{file_path}': {e}")

            row = self.list_pages.currentRow()
            self.list_pages.takeItem(row)
            if self.list_pages.count() > 0:
                new_row = min(row, self.list_pages.count() - 1)
                self.list_pages.setCurrentRow(new_row)
            else:
                self.current_page_name = None
                self.lbl_active_page_title.setText("No Page Selected")
                self.txt_editor.setPlainText("")
                self._update_preview("")

    def closeEvent(self, event):
        """Auto-save active page on window close."""
        if self.current_page_name:
            self._save_page_to_disk(self.current_page_name, self.txt_editor.toPlainText())
        event.accept()
