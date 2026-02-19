from __future__ import annotations
from PySide6 import QtWidgets, QtCore, QtGui
from typing import Dict, List, Any
import json
from pathlib import Path
from uuid import uuid4

from app_paths import DIALOG_FP, DIALOGMETA, DIALOG_DIR, DIALOG_BLOCKS
from helpers import safe_json, write_json

class DialogTab(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QMainWindow):
        super().__init__()
        self.parent = parent
        self.dialog_blocks: List[Dict] = []
        self.dialog_index: int = -1
        self._dialog_edit_row: int | None = None
        
        self._build_ui()
        self._wire_signals()
        self._load_dialog()

    def _build_ui(self):
        v_layout = QtWidgets.QVBoxLayout(self)
        
        # Search & Add Section
        h_search = QtWidgets.QHBoxLayout()
        self.searchDialog = QtWidgets.QLineEdit()
        self.searchDialog.setPlaceholderText("Search & Add Dialog...")
        self.btn_add_block = QtWidgets.QPushButton("Add Block")
        h_search.addWidget(self.searchDialog)
        h_search.addWidget(self.btn_add_block)
        v_layout.addLayout(h_search)
        
        # Dialog List
        self.listDialog = QtWidgets.QListWidget()
        self.listDialog.setAlternatingRowColors(True)
        self.listDialog.setUniformItemSizes(True)
        self.listDialog.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.listDialog.customContextMenuRequested.connect(self._show_dialog_context_menu)
        v_layout.addWidget(self.listDialog)
        
        # Dialog Preview
        self.dialog_preview = QtWidgets.QTextEdit()
        self.dialog_preview.setReadOnly(True)
        v_layout.addWidget(self.dialog_preview)
        
        # Controls & Info
        h_ctrls = QtWidgets.QHBoxLayout()
        self.btnPrev = QtWidgets.QPushButton("◄ Previous")
        self.btnPrev.setMinimumWidth(100)
        self.btnPrev.setProperty("class", "primary")
        self.btnNext = QtWidgets.QPushButton("Next ►")
        self.btnNext.setMinimumWidth(100)
        self.btnNext.setProperty("class", "primary")
        self.lblDialogHud = QtWidgets.QLabel("Dialog: - / - — Speaker: —")
        h_ctrls.addWidget(self.btnPrev)
        h_ctrls.addWidget(self.btnNext)
        h_ctrls.addWidget(self.lblDialogHud)
        h_ctrls.addStretch(1)
        v_layout.addLayout(h_ctrls)

    def _wire_signals(self):
        self.btn_add_block.clicked.connect(self._add_dialog_block)
        self.listDialog.currentRowChanged.connect(self._on_dialog_row_changed)
        self.listDialog.itemDoubleClicked.connect(self._edit_dialog_block)
        self.btnNext.clicked.connect(self._dialog_next_local)
        self.btnPrev.clicked.connect(self._dialog_prev_local)

    def _on_dialog_row_changed(self, new_row: int):
        if 0 <= new_row < len(self.dialog_blocks):
            self.dialog_index = new_row
            self._update_dialog_hud()
            self.dialog_preview.setText(self.dialog_blocks[new_row].get("text", ""))
            # inform parent window so it can persist overlay state if needed
            if hasattr(self.parent, "_on_dialog_row_changed"):
                self.parent._on_dialog_row_changed(new_row)

    def _update_dialog_hud(self):
        idx = self.dialog_index
        total = len(self.dialog_blocks)
        speaker = "—"
        if 0 <= idx < total:
            speaker = self.dialog_blocks[idx].get("speaker", "—")
        self.lblDialogHud.setText(f"Dialog: {idx+1} / {total} — Speaker: {speaker}")

    def _load_dialog(self):
        # Prefer rich dialog_blocks file if present (with stable IDs), else migrate from legacy files.
        blocks: List[Dict[str, Any]] = []
        raw = safe_json(DIALOG_BLOCKS, None)
        if isinstance(raw, list):
            for b in raw:
                text = str(b.get("text", "")).strip()
                if not text:
                    continue
                blocks.append({
                    "id": b.get("id") or str(uuid4()),
                    "text": text,
                    "speaker": b.get("speaker", ""),
                    "time": b.get("time", ""),
                })
        if not blocks:
            # Legacy migration path: dialog.txt + dialog_meta.json keyed by full text.
            try:
                with open(DIALOG_FP, "r", encoding="utf-8") as f:
                    content = f.read()
                    chunks = content.split("\n---\n")
                    meta = safe_json(DIALOGMETA, {})
                    for t in chunks:
                        t = t.strip()
                        if not t:
                            continue
                        info = meta.get(t, {}) if isinstance(meta, dict) else {}
                        blocks.append({
                            "id": info.get("id") or str(uuid4()),
                            "text": t,
                            "speaker": info.get("speaker", ""),
                            "time": info.get("time", ""),
                        })
            except FileNotFoundError:
                blocks = []
        self.dialog_blocks = blocks
        
        self._refresh_dialog_list()
        self._update_dialog_hud()
        self.parent._log("Dialog loaded from file.")
        
    def _refresh_dialog_list(self):
        self.listDialog.clear()
        for i, block in enumerate(self.dialog_blocks):
            label = f"{i+1}. {block.get('speaker')}: {block.get('text', '')[:40]}..."
            self.listDialog.addItem(label)
        
        if self.dialog_blocks and self.dialog_index >= 0:
            self.listDialog.setCurrentRow(self.dialog_index)

    def _add_dialog_block(self):
        text = self.searchDialog.text().strip()
        if not text:
            return
        
        new_block = {"id": str(uuid4()), "text": text, "speaker": "", "time": ""}
        self.dialog_blocks.append(new_block)
        self._persist_dialog()
        self._refresh_dialog_list()
        self.parent._log("Added new dialog block.")
        self.searchDialog.clear()

    def _persist_dialog(self):
        # Ensure every block has a stable ID
        for b in self.dialog_blocks:
            if not b.get("id"):
                b["id"] = str(uuid4())

        # Plain text file consumed by overlay
        text_content = "\n---\n".join([b["text"] for b in self.dialog_blocks])
        with open(DIALOG_FP, "w", encoding="utf-8") as f:
            f.write(text_content)
        
        # Legacy meta (for backwards compatibility, keyed by text)
        meta = {
            b["text"]: {
                "id": b.get("id"),
                "speaker": b.get("speaker"),
                "time": b.get("time"),
            }
            for b in self.dialog_blocks
        }
        write_json(DIALOGMETA, meta)

        # Rich blocks file with stable IDs
        write_json(DIALOG_BLOCKS, [
            {
                "id": b["id"],
                "text": b["text"],
                "speaker": b.get("speaker", ""),
                "time": b.get("time", ""),
            }
            for b in self.dialog_blocks
        ])

    def _dialog_next_local(self):
        if not self.dialog_blocks:
            return
        
        self.dialog_index = (self.dialog_index + 1) % len(self.dialog_blocks)
        self.listDialog.setCurrentRow(self.dialog_index)
        self._persist_dialog_state()

    def _dialog_prev_local(self):
        if not self.dialog_blocks:
            return
        
        self.dialog_index = (self.dialog_index - 1 + len(self.dialog_blocks)) % len(self.dialog_blocks)
        self.listDialog.setCurrentRow(self.dialog_index)
        self._persist_dialog_state()

    def _persist_dialog_state(self):
        # A simple state persistence for the overlay to read
        state = {"index": self.dialog_index}
        write_json(DIALOG_FP.with_suffix(".json"), state)

    def _dialog_make_current(self):
        row = self.listDialog.currentRow()
        if 0 <= row < len(self.dialog_blocks):
            self.dialog_index = row
            self._persist_dialog_state()
            self._update_dialog_hud()
            self.parent._log(f"Dialog current index set to {row+1}.")
    
    def _show_dialog_context_menu(self, pos):
        """Show context menu for dialog list items."""
        item = self.listDialog.itemAt(pos)
        if not item:
            return
        menu = QtWidgets.QMenu(self)
        act_edit = menu.addAction("Edit…")
        act_delete = menu.addAction("Delete")
        act_duplicate = menu.addAction("Duplicate")
        action = menu.exec_(self.listDialog.mapToGlobal(pos))
        row = self.listDialog.row(item)
        if action == act_edit:
            self._edit_dialog_block(row)
        elif action == act_delete:
            self._delete_dialog_block(row)
        elif action == act_duplicate:
            self._duplicate_dialog_block(row)
    
    def _edit_dialog_block(self, row=None):
        """Edit a dialog block."""
        if row is None:
            row = self.listDialog.currentRow()
        if not (0 <= row < len(self.dialog_blocks)):
            return
        block = self.dialog_blocks[row]
        text, ok = QtWidgets.QInputDialog.getMultiLineText(
            self, "Edit Dialog Block", "Dialog Text:", block.get("text", "")
        )
        if ok and text.strip():
            block["text"] = text.strip()
            self._persist_dialog()
            self._refresh_dialog_list()
            self.listDialog.setCurrentRow(row)
            self.parent._log(f"Edited dialog block {row+1}.")
    
    def _delete_dialog_block(self, row):
        """Delete a dialog block."""
        if not (0 <= row < len(self.dialog_blocks)):
            return
        reply = QtWidgets.QMessageBox.question(
            self, "Delete Dialog Block",
            f"Delete dialog block {row+1}?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )
        if reply == QtWidgets.QMessageBox.Yes:
            self.dialog_blocks.pop(row)
            if self.dialog_index >= len(self.dialog_blocks):
                self.dialog_index = max(0, len(self.dialog_blocks) - 1)
            self._persist_dialog()
            self._persist_dialog_state()
            self._refresh_dialog_list()
            self.parent._log(f"Deleted dialog block {row+1}.")
    
    def _duplicate_dialog_block(self, row):
        """Duplicate a dialog block."""
        if not (0 <= row < len(self.dialog_blocks)):
            return
        from uuid import uuid4
        original = self.dialog_blocks[row]
        new_block = {
            "id": str(uuid4()),
            "text": original.get("text", ""),
            "speaker": original.get("speaker", ""),
            "time": original.get("time", ""),
        }
        self.dialog_blocks.insert(row + 1, new_block)
        self._persist_dialog()
        self._refresh_dialog_list()
        self.listDialog.setCurrentRow(row + 1)
        self.parent._log(f"Duplicated dialog block {row+1}.")
