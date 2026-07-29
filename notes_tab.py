from __future__ import annotations
from PySide6 import QtWidgets, QtCore
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel
from pathlib import Path
import markdown

from app_paths import VAULT_DIR
from helpers import atomic_write_text
from styles import MD_CSS

class NotesTab(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QMainWindow):
        super().__init__()
        self.parent = parent
        self._notes_files = []
        self._current_note_fp: Path | None = None
        self._current_note_row = -1
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
        
    def _load_notes_list(self, select_fp: Path | None = None):
        old = self.notes_list.blockSignals(True)
        self.notes_list.clear()
        self._notes_files = sorted(VAULT_DIR.glob("*.md"))
        for fp in self._notes_files:
            self.notes_list.addItem(fp.stem)
        target = select_fp or self._current_note_fp
        row = self._notes_files.index(target) if target in self._notes_files else (0 if self._notes_files else -1)
        self.notes_list.setCurrentRow(row)
        self.notes_list.blockSignals(old)
        if row >= 0 and (self._current_note_fp != self._notes_files[row] or self._current_note_row != row):
            self._on_note_selected(row)

    def _on_note_selected(self, row: int):
        if not (0 <= row < len(self._notes_files)):
            return
        if self._current_note_fp == self._notes_files[row] and self._current_note_row == row:
            return
        if not self._confirm_unsaved_changes():
            old = self.notes_list.blockSignals(True)
            self.notes_list.setCurrentRow(self._current_note_row)
            self.notes_list.blockSignals(old)
            return
        next_fp = self._notes_files[row]
        try:
            with next_fp.open("r", encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeError) as e:
            QtWidgets.QMessageBox.critical(self, "Open Note Failed", str(e))
            old = self.notes_list.blockSignals(True)
            self.notes_list.setCurrentRow(self._current_note_row)
            self.notes_list.blockSignals(old)
            return
        self._current_note_fp = next_fp
        self._current_note_row = row
        self.editor.setPlainText(text)
        self._saved_content = text  # Track what's saved
        self._update_preview()

    def _confirm_unsaved_changes(self) -> bool:
        if not self.has_unsaved_changes():
            return True
        reply = QtWidgets.QMessageBox.question(
            self,
            "Unsaved Changes",
            "Save changes to the current note before switching?",
            QtWidgets.QMessageBox.Save | QtWidgets.QMessageBox.Discard | QtWidgets.QMessageBox.Cancel,
            QtWidgets.QMessageBox.Save,
        )
        if reply == QtWidgets.QMessageBox.Save:
            return self._save_note()
        if reply == QtWidgets.QMessageBox.Discard:
            return True
        return False

    def _save_note(self):
        if not self._current_note_fp:
            self._new_note()
            return bool(self._current_note_fp)
        
        content = self.editor.toPlainText()
        try:
            atomic_write_text(self._current_note_fp, content, encoding="utf-8")
        except OSError as e:
            QtWidgets.QMessageBox.critical(self, "Save Note Failed", str(e))
            return False
        self._saved_content = content  # Update saved content tracker
        self.parent._log(f"Saved note: {self._current_note_fp.name}")
        return True
    
    def has_unsaved_changes(self) -> bool:
        """Check if current note has unsaved changes."""
        if not self._current_note_fp:
            return False
        return self.editor.toPlainText() != self._saved_content

    def _new_note(self):
        name, ok = QtWidgets.QInputDialog.getText(self, "New Note", "Note Name:")
        if not ok or not name:
            return
        if not self._confirm_unsaved_changes():
            return
        
        new_fp = VAULT_DIR / f"{name.strip()}.md"
        if new_fp.exists():
            QtWidgets.QMessageBox.warning(self, "Note Exists", "A note with this name already exists.")
            return

        initial_content = "# " + name.strip() + "\n"
        try:
            atomic_write_text(new_fp, initial_content, encoding="utf-8")
        except OSError as e:
            QtWidgets.QMessageBox.critical(self, "Create Note Failed", str(e))
            return
        
        # The user already resolved the current note before this new file was created.
        self._saved_content = self.editor.toPlainText()
        self._load_notes_list(select_fp=new_fp)
        # New note is already saved, so track it
        self._saved_content = initial_content
        
    def _update_preview(self):
        html = markdown.markdown(self.editor.toPlainText())
        html = f"<html><head>{MD_CSS}</head><body>{html}</body></html>"
        self.preview.setHtml(html)
