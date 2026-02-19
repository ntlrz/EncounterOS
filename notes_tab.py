from __future__ import annotations
from PySide6 import QtWidgets, QtCore
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel
from pathlib import Path
import markdown
import re

from app_paths import VAULT_DIR
from styles import MD_CSS

class NotesTab(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QMainWindow):
        super().__init__()
        self.parent = parent
        self._notes_files = []
        self._current_note_fp: Path | None = None
        self._saved_content = ""  # Track saved content to detect unsaved changes
        self._build_ui()
        self._load_notes_list()

    def _build_ui(self):
        h_layout = QtWidgets.QHBoxLayout(self)
        
        # Notes list and buttons on the left
        v_list_layout = QtWidgets.QVBoxLayout()
        self.notes_list = QtWidgets.QListWidget()
        self.notes_list.setMinimumWidth(200)
        v_list_layout.addWidget(self.notes_list)
        
        h_buttons = QtWidgets.QHBoxLayout()
        self.btnNew = QtWidgets.QPushButton("New")
        self.btnSave = QtWidgets.QPushButton("Save")
        h_buttons.addWidget(self.btnNew)
        h_buttons.addWidget(self.btnSave)
        v_list_layout.addLayout(h_buttons)
        
        h_layout.addLayout(v_list_layout, 1)

        # Markdown editor on the right
        v_editor_layout = QtWidgets.QVBoxLayout()
        self.editor = QtWidgets.QTextEdit()
        self.editor.setPlaceholderText("Write your notes in Markdown here...")
        v_editor_layout.addWidget(self.editor)
        
        self.preview = QWebEngineView()
        self.preview.setMinimumHeight(200)
        v_editor_layout.addWidget(self.preview)
        
        h_layout.addLayout(v_editor_layout, 3)
        
        # Signals
        self.notes_list.currentRowChanged.connect(self._on_note_selected)
        self.editor.textChanged.connect(self._update_preview)
        self.btnSave.clicked.connect(self._save_note)
        self.btnNew.clicked.connect(self._new_note)
        
    def _load_notes_list(self):
        self.notes_list.clear()
        self._notes_files = sorted(VAULT_DIR.glob("*.md"))
        for fp in self._notes_files:
            self.notes_list.addItem(fp.stem)
        
        if self._notes_files:
            self.notes_list.setCurrentRow(0)

    def _on_note_selected(self, row: int):
        if 0 <= row < len(self._notes_files):
            self._current_note_fp = self._notes_files[row]
            with self._current_note_fp.open("r", encoding="utf-8") as f:
                text = f.read()
                self.editor.setPlainText(text)
                self._saved_content = text  # Track what's saved
                self._update_preview()

    def _save_note(self):
        if not self._current_note_fp:
            self._new_note()
            if not self._current_note_fp: return
        
        content = self.editor.toPlainText()
        with self._current_note_fp.open("w", encoding="utf-8") as f:
            f.write(content)
        self._saved_content = content  # Update saved content tracker
        self.parent._log(f"Saved note: {self._current_note_fp.name}")
    
    def has_unsaved_changes(self) -> bool:
        """Check if current note has unsaved changes."""
        if not self._current_note_fp:
            return False
        return self.editor.toPlainText() != self._saved_content

    def _new_note(self):
        name, ok = QtWidgets.QInputDialog.getText(self, "New Note", "Note Name:")
        if not ok or not name:
            return
        
        new_fp = VAULT_DIR / f"{name.strip()}.md"
        if new_fp.exists():
            QtWidgets.QMessageBox.warning(self, "Note Exists", "A note with this name already exists.")
            return

        initial_content = "# " + name.strip() + "\n"
        with new_fp.open("w", encoding="utf-8") as f:
            f.write(initial_content)
        
        self._load_notes_list()
        self.notes_list.setCurrentRow(self.notes_list.count() - 1)
        # New note is already saved, so track it
        self._saved_content = initial_content
        
    def _update_preview(self):
        html = markdown.markdown(self.editor.toPlainText())
        html = f"<html><head>{MD_CSS}</head><body>{html}</body></html>"
        self.preview.setHtml(html)