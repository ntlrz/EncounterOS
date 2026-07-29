from __future__ import annotations
from PySide6 import QtWidgets, QtCore, QtGui
from typing import Dict, List, Any
import json
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from app_paths import DIALOG_FP, DIALOGMETA, DIALOG_DIR, DIALOG_BLOCKS
from helpers import atomic_write_text, load_json, write_json
from portrait_library import DialogBlockEditor, PORTRAIT_SOURCE_DIR_FIELD


class DialogListWidget(QtWidgets.QListWidget):
    rowsReordered = QtCore.Signal(list)

    def dropEvent(self, event):
        super().dropEvent(event)
        self.rowsReordered.emit([
            self.item(index).data(QtCore.Qt.UserRole)
            for index in range(self.count())
        ])


def parse_dialog_blocks_document(data: Any) -> List[Dict[str, Any]]:
    if not isinstance(data, list):
        raise ValueError("dialog blocks document must be a JSON list")
    blocks: List[Dict[str, Any]] = []
    for block in data:
        if not isinstance(block, dict):
            raise ValueError("each dialog block must be a JSON object")
        text = str(block.get("text", "")).strip()
        if not text:
            continue
        normalized = dict(block)
        normalized.update({
            "id": block.get("id") or str(uuid4()),
            "text": text,
            "speaker": block.get("speaker", ""),
            "time": block.get("time", ""),
        })
        blocks.append(normalized)
    return blocks

class DialogTab(QtWidgets.QWidget):
    progressionChanged = QtCore.Signal()

    def __init__(self, parent: QtWidgets.QMainWindow):
        super().__init__()
        self.parent = parent
        self.dialog_blocks: List[Dict] = []
        self.dialog_index: int = -1
        self._dialog_edit_row: int | None = None
        self._dialog_write_blocked = False
        self._dialog_state_write_blocked = False
        self._dialog_write_warning_shown = False
        self._dialog_meta_document: Dict = {}
        
        self._build_ui()
        self._wire_signals()
        self._load_dialog()

    def _build_ui(self):
        v_layout = QtWidgets.QVBoxLayout(self)
        
        # New-block seed text remains available for the global focus shortcut.
        h_search = QtWidgets.QHBoxLayout()
        self.searchDialog = QtWidgets.QLineEdit()
        self.searchDialog.setPlaceholderText("Optional starting text for New…")
        self.btn_add_block = QtWidgets.QPushButton("New…")
        h_search.addWidget(self.searchDialog)
        h_search.addWidget(self.btn_add_block)
        v_layout.addLayout(h_search)

        actions = QtWidgets.QHBoxLayout()
        self.btnEdit = QtWidgets.QPushButton("Edit…")
        self.btnDuplicate = QtWidgets.QPushButton("Duplicate")
        self.btnDelete = QtWidgets.QPushButton("Delete")
        self.btnMoveUp = QtWidgets.QPushButton("Move Up")
        self.btnMoveDown = QtWidgets.QPushButton("Move Down")
        self.btnMakeCurrent = QtWidgets.QPushButton("Make Current")
        for button in (
            self.btnEdit, self.btnDuplicate, self.btnDelete,
            self.btnMoveUp, self.btnMoveDown, self.btnMakeCurrent,
        ):
            actions.addWidget(button)
        actions.addStretch(1)
        v_layout.addLayout(actions)
        
        # Dialog List
        self.listDialog = DialogListWidget()
        self.listDialog.setAlternatingRowColors(True)
        self.listDialog.setUniformItemSizes(False)
        self.listDialog.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        self.listDialog.setDefaultDropAction(QtCore.Qt.MoveAction)
        self.listDialog.setDropIndicatorShown(True)
        self.listDialog.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.listDialog.customContextMenuRequested.connect(self._show_dialog_context_menu)
        v_layout.addWidget(self.listDialog)
        
        # Dialog Preview
        self.dialog_preview = QtWidgets.QTextEdit()
        self.dialog_preview.setReadOnly(True)
        v_layout.addWidget(self.dialog_preview)
        
        # Local status only; live progression is controlled by GMWindow.
        h_ctrls = QtWidgets.QHBoxLayout()
        self.lblDialogHud = QtWidgets.QLabel("Dialog: - / - — Speaker: —")
        h_ctrls.addWidget(self.lblDialogHud)
        h_ctrls.addStretch(1)
        v_layout.addLayout(h_ctrls)

    def _wire_signals(self):
        self.btn_add_block.clicked.connect(lambda: self._add_dialog_block())
        self.listDialog.currentRowChanged.connect(self._on_dialog_row_changed)
        self.listDialog.itemDoubleClicked.connect(
            lambda item, _column=0: self._edit_dialog_block(self.listDialog.row(item))
        )
        self.listDialog.rowsReordered.connect(self._apply_drag_order)
        self.btnEdit.clicked.connect(lambda: self._edit_dialog_block())
        self.btnDuplicate.clicked.connect(
            lambda: self._duplicate_dialog_block(self.listDialog.currentRow())
        )
        self.btnDelete.clicked.connect(
            lambda: self._delete_dialog_block(self.listDialog.currentRow())
        )
        self.btnMoveUp.clicked.connect(lambda: self._move_dialog_block(-1))
        self.btnMoveDown.clicked.connect(lambda: self._move_dialog_block(1))
        self.btnMakeCurrent.clicked.connect(self._dialog_make_current)
        self._move_up_shortcut = QtGui.QShortcut(
            QtGui.QKeySequence("Alt+Up"), self,
            activated=lambda: self._move_dialog_block(-1),
        )
        self._move_down_shortcut = QtGui.QShortcut(
            QtGui.QKeySequence("Alt+Down"), self,
            activated=lambda: self._move_dialog_block(1),
        )

    def _on_dialog_row_changed(self, new_row: int):
        if 0 <= new_row < len(self.dialog_blocks):
            self.dialog_preview.setText(self.dialog_blocks[new_row].get("text", ""))
        else:
            self.dialog_preview.clear()
        self._sync_action_states()

    def _update_dialog_hud(self):
        idx = self.dialog_index
        total = len(self.dialog_blocks)
        if 0 <= idx < total:
            speaker = self.dialog_blocks[idx].get("speaker") or "Narrator"
            self.lblDialogHud.setText(
                f"Live: {idx + 1} / {total} — Speaker: {speaker}"
            )
        else:
            self.lblDialogHud.setText(f"Live: none — {total} prepared")
        self.progressionChanged.emit()

    def _load_dialog(self):
        # Prefer rich dialog_blocks file if present (with stable IDs), else migrate from legacy files.
        blocks: List[Dict[str, Any]] = []
        blocks_result = load_json(DIALOG_BLOCKS)
        if blocks_result.valid:
            try:
                blocks = parse_dialog_blocks_document(blocks_result.data)
            except ValueError as e:
                self._dialog_write_blocked = True
                self.parent._log(f"Dialog blocks were not loaded: {e}")
        elif not blocks_result.missing:
            self._dialog_write_blocked = True
            self.parent._log(f"Dialog blocks were not loaded: {blocks_result.error}")
        if not blocks:
            # Legacy migration path: dialog.txt + dialog_meta.json keyed by full text.
            try:
                with open(DIALOG_FP, "r", encoding="utf-8") as f:
                    content = f.read()
                    chunks = content.split("\n---\n")
                    meta_result = load_json(DIALOGMETA)
                    if meta_result.valid and isinstance(meta_result.data, dict):
                        meta = dict(meta_result.data)
                        self._dialog_meta_document = dict(meta)
                    elif meta_result.missing:
                        meta = {}
                    else:
                        meta = {}
                        self._dialog_write_blocked = True
                        self.parent._log("Dialog metadata was not loaded safely.")
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
            except (OSError, UnicodeError) as e:
                blocks = []
                self._dialog_write_blocked = True
                self.parent._log(f"Legacy dialog text was not loaded: {e}")
        self.dialog_blocks = blocks

        state_result = load_json(DIALOG_FP.with_suffix(".json"))
        if state_result.valid and isinstance(state_result.data, dict):
            index = state_result.data.get("index", -1)
            if isinstance(index, int) and not isinstance(index, bool):
                self.dialog_index = index
            else:
                self._dialog_state_write_blocked = True
                self.parent._log("Dialog index was not loaded: 'index' must be an integer.")
        elif not state_result.missing:
            self._dialog_state_write_blocked = True
            self.parent._log("Dialog index was not loaded safely.")
        
        self._refresh_dialog_list()
        self._update_dialog_hud()
        self.parent._log("Dialog loaded from file.")
        
    def _refresh_dialog_list(self, selected_id: str | None = None):
        if selected_id is None:
            selected = self.listDialog.currentItem()
            selected_id = (
                selected.data(QtCore.Qt.UserRole) if selected is not None else None
            )
        self.listDialog.clear()
        for i, block in enumerate(self.dialog_blocks):
            speaker = str(block.get("speaker") or "Narrator")
            preview = " ".join(str(block.get("text") or "").split())
            if len(preview) > 90:
                preview = preview[:87] + "…"
            markers = []
            if i == self.dialog_index:
                markers.append("LIVE")
            if i == self.dialog_index + 1:
                markers.append("NEXT")
            marker = f"[{' / '.join(markers)}] " if markers else ""
            portrait = " ◉" if block.get("portrait") or block.get("portrait_id") else ""
            item = QtWidgets.QListWidgetItem(
                f"{marker}{i + 1}  {speaker}{portrait}\n{preview}"
            )
            item.setData(QtCore.Qt.UserRole, block.get("id"))
            item.setSizeHint(QtCore.QSize(0, self.listDialog.fontMetrics().lineSpacing() * 2 + 10))
            if i == self.dialog_index:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            self.listDialog.addItem(item)
            if block.get("id") == selected_id:
                self.listDialog.setCurrentItem(item)
        self._update_dialog_hud()
        self._sync_action_states()

    def _sync_action_states(self):
        row = self.listDialog.currentRow()
        valid = 0 <= row < len(self.dialog_blocks)
        for button in (
            self.btnEdit, self.btnDuplicate, self.btnDelete, self.btnMakeCurrent,
        ):
            button.setEnabled(valid)
        self.btnMoveUp.setEnabled(valid and row > 0)
        self.btnMoveDown.setEnabled(valid and row < len(self.dialog_blocks) - 1)

    def _add_dialog_block(self, insert_at: int | None = None):
        row = self.listDialog.currentRow()
        if insert_at is None:
            insert_at = row + 1 if 0 <= row < len(self.dialog_blocks) else len(self.dialog_blocks)
        new_block = {
            "id": str(uuid4()),
            "text": self.searchDialog.text(),
            "speaker": "",
            "time": "",
        }
        editor = DialogBlockEditor(
            new_block, self._portrait_entities(), self, title="New Dialog Block"
        )
        if not editor.exec():
            return
        payload = editor.payload()
        if not payload.get("text"):
            return
        self.dialog_blocks.insert(max(0, min(insert_at, len(self.dialog_blocks))), payload)
        if self._persist_dialog():
            self._refresh_dialog_list(payload["id"])
            self.listDialog.scrollToItem(self.listDialog.currentItem())
            self.parent._log("Added new dialog block.")
            self.searchDialog.clear()

    def _persist_dialog(self):
        current_blocks = load_json(DIALOG_BLOCKS)
        if current_blocks.valid:
            try:
                parse_dialog_blocks_document(current_blocks.data)
            except ValueError:
                self._dialog_write_blocked = True
        elif not current_blocks.missing:
            self._dialog_write_blocked = True
        current_meta = load_json(DIALOGMETA)
        if current_meta.valid:
            if isinstance(current_meta.data, dict):
                self._dialog_meta_document = dict(current_meta.data)
            else:
                self._dialog_write_blocked = True
        elif not current_meta.valid and not current_meta.missing:
            self._dialog_write_blocked = True
        if self._dialog_write_blocked:
            if not self._dialog_write_warning_shown:
                self.parent._toast(
                    "Dialog changes are not being saved because a dialog source could not be loaded safely."
                )
                self._dialog_write_warning_shown = True
            return False
        # Ensure every block has a stable ID
        for b in self.dialog_blocks:
            if not b.get("id"):
                b["id"] = str(uuid4())

        # Plain text file consumed by overlay
        text_content = "\n---\n".join([b["text"] for b in self.dialog_blocks])
        atomic_write_text(DIALOG_FP, text_content, encoding="utf-8")
        
        # Legacy meta (for backwards compatibility, keyed by text)
        meta = dict(self._dialog_meta_document)
        for b in self.dialog_blocks:
            entry = dict(meta.get(b["text"], {})) if isinstance(meta.get(b["text"]), dict) else {}
            entry.update({
                "id": b.get("id"),
                "speaker": b.get("speaker"),
                "time": b.get("time"),
            })
            meta[b["text"]] = entry
        write_json(DIALOGMETA, meta)
        self._dialog_meta_document = dict(meta)

        # Rich blocks file with stable IDs
        write_json(DIALOG_BLOCKS, [dict(b) for b in self.dialog_blocks])
        return True

    def _dialog_next_local(self):
        if not self.dialog_blocks:
            return
        if self.dialog_index < 0:
            self.dialog_index = 0
        elif self.dialog_index < len(self.dialog_blocks) - 1:
            self.dialog_index += 1
        else:
            self.parent._toast("End of dialog sequence.")
            return
        self._persist_dialog_state()
        self._refresh_dialog_list()
        self.listDialog.scrollToItem(self.listDialog.item(self.dialog_index))

    def _dialog_prev_local(self):
        if not self.dialog_blocks:
            return
        if self.dialog_index > 0:
            self.dialog_index -= 1
        else:
            self.parent._toast("Start of dialog sequence.")
            return
        self._persist_dialog_state()
        self._refresh_dialog_list()
        self.listDialog.scrollToItem(self.listDialog.item(self.dialog_index))

    def _persist_dialog_state(self):
        # A simple state persistence for the overlay to read
        if self._dialog_state_write_blocked:
            self.parent._toast(
                f"Dialog position not saved because {DIALOG_FP.with_suffix('.json').name} is invalid."
            )
            return False
        result = load_json(DIALOG_FP.with_suffix(".json"))
        if result.valid and isinstance(result.data, dict):
            state = dict(result.data)
        elif result.missing:
            state = {}
        else:
            self._dialog_state_write_blocked = True
            self.parent._toast(
                f"Dialog position not saved because {DIALOG_FP.with_suffix('.json').name} is invalid."
            )
            return False
        state["index"] = self.dialog_index
        write_json(DIALOG_FP.with_suffix(".json"), state)
        return True

    def _dialog_make_current(self):
        row = self.listDialog.currentRow()
        if 0 <= row < len(self.dialog_blocks):
            self.dialog_index = row
            self._persist_dialog_state()
            selected_id = self.dialog_blocks[row].get("id")
            self._refresh_dialog_list(selected_id)
            self.parent._log(f"Dialog current index set to {row+1}.")

    def _move_dialog_block(self, delta: int):
        row = self.listDialog.currentRow()
        target = row + delta
        if not (0 <= row < len(self.dialog_blocks) and 0 <= target < len(self.dialog_blocks)):
            return
        selected_id = self.dialog_blocks[row].get("id")
        live_id = (
            self.dialog_blocks[self.dialog_index].get("id")
            if 0 <= self.dialog_index < len(self.dialog_blocks)
            else None
        )
        self.dialog_blocks[row], self.dialog_blocks[target] = (
            self.dialog_blocks[target], self.dialog_blocks[row]
        )
        self.dialog_index = next(
            (
                index for index, block in enumerate(self.dialog_blocks)
                if block.get("id") == live_id
            ),
            -1,
        )
        if self._persist_dialog():
            self._persist_dialog_state()
            self._refresh_dialog_list(selected_id)

    def _apply_drag_order(self, ordered_ids: list):
        by_id = {block.get("id"): block for block in self.dialog_blocks}
        if len(ordered_ids) != len(self.dialog_blocks) or any(
            block_id not in by_id for block_id in ordered_ids
        ):
            self._refresh_dialog_list()
            return
        live_id = (
            self.dialog_blocks[self.dialog_index].get("id")
            if 0 <= self.dialog_index < len(self.dialog_blocks)
            else None
        )
        selected = self.listDialog.currentItem()
        selected_id = selected.data(QtCore.Qt.UserRole) if selected else None
        self.dialog_blocks = [by_id[block_id] for block_id in ordered_ids]
        self.dialog_index = next(
            (
                index for index, block in enumerate(self.dialog_blocks)
                if block.get("id") == live_id
            ),
            -1,
        )
        if self._persist_dialog():
            self._persist_dialog_state()
        self._refresh_dialog_list(selected_id)
    
    def _show_dialog_context_menu(self, pos):
        """Show context menu for dialog list items."""
        item = self.listDialog.itemAt(pos)
        if not item:
            return
        self.listDialog.setCurrentItem(item)
        menu = QtWidgets.QMenu(self)
        act_current = menu.addAction("Make Current")
        act_edit = menu.addAction("Edit…")
        act_duplicate = menu.addAction("Duplicate")
        menu.addSeparator()
        act_before = menu.addAction("Insert Before…")
        act_after = menu.addAction("Insert After…")
        act_up = menu.addAction("Move Up")
        act_down = menu.addAction("Move Down")
        menu.addSeparator()
        act_delete = menu.addAction("Delete")
        row = self.listDialog.row(item)
        act_up.setEnabled(row > 0)
        act_down.setEnabled(row < len(self.dialog_blocks) - 1)
        action = menu.exec_(self.listDialog.mapToGlobal(pos))
        if action == act_current:
            self._dialog_make_current()
        elif action == act_edit:
            self._edit_dialog_block(row)
        elif action == act_duplicate:
            self._duplicate_dialog_block(row)
        elif action == act_before:
            self._add_dialog_block(row)
        elif action == act_after:
            self._add_dialog_block(row + 1)
        elif action == act_up:
            self._move_dialog_block(-1)
        elif action == act_down:
            self._move_dialog_block(1)
        elif action == act_delete:
            self._delete_dialog_block(row)
    
    def _edit_dialog_block(self, row=None):
        """Edit a dialog block."""
        if row is None:
            row = self.listDialog.currentRow()
        if not (0 <= row < len(self.dialog_blocks)):
            return
        block = self.dialog_blocks[row]
        editor = DialogBlockEditor(block, self._portrait_entities(), self)
        if editor.exec():
            payload = editor.payload()
            if not payload.get("text"):
                return
            self.dialog_blocks[row] = payload
            self._persist_dialog()
            self._refresh_dialog_list(payload.get("id"))
            self.parent._log(f"Edited dialog block {row+1}.")

    def _portrait_entities(self) -> List[Dict]:
        """Return live and already-loaded roster entities without mutating sources."""
        entities: List[Dict] = []
        combat_tab = getattr(self.parent, "combat_tab", None)
        entities.extend(deepcopy(getattr(combat_tab, "combatants", []) or []))
        rosters_tab = getattr(self.parent, "rosters_tab", None)
        for pack in getattr(rosters_tab, "_packs", []) or []:
            source = pack.get("file")
            source_dir = str(Path(source).resolve().parent) if source else None
            for raw in pack.get("entries", []) or []:
                if not isinstance(raw, dict):
                    continue
                entity = deepcopy(raw)
                if source_dir:
                    entity.setdefault(PORTRAIT_SOURCE_DIR_FIELD, source_dir)
                entities.append(entity)
        return entities
    
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
            removed = self.dialog_blocks[row]
            live_id = (
                self.dialog_blocks[self.dialog_index].get("id")
                if 0 <= self.dialog_index < len(self.dialog_blocks)
                else None
            )
            self.dialog_blocks.pop(row)
            if removed.get("id") == live_id:
                self.dialog_index = -1
            else:
                self.dialog_index = next(
                    (
                        index for index, block in enumerate(self.dialog_blocks)
                        if block.get("id") == live_id
                    ),
                    -1,
                )
            self._persist_dialog()
            self._persist_dialog_state()
            self._refresh_dialog_list()
            self.parent._log(f"Deleted dialog block {row+1}.")
    
    def _duplicate_dialog_block(self, row):
        """Duplicate a dialog block."""
        if not (0 <= row < len(self.dialog_blocks)):
            return
        original = self.dialog_blocks[row]
        new_block = deepcopy(original)
        new_block["id"] = str(uuid4())
        self.dialog_blocks.insert(row + 1, new_block)
        self._persist_dialog()
        self._refresh_dialog_list(new_block["id"])
        self.parent._log(f"Duplicated dialog block {row+1}.")
