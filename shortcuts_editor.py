# shortcuts_editor.py — Rebindable keyboard shortcuts; config load/save and editor dialog.

from __future__ import annotations
from PySide6 import QtWidgets, QtGui, QtCore
from typing import Dict, Callable, List

# Default key bindings (used when config missing or for Reset)
DEFAULT_SHORTCUTS: Dict[str, str] = {
    "toggle_overlay": "F4",
    "advance_turn": "F5",
    "previous_turn": "F7",
    "toggle_mode": "F6",
    "focus_search": "/",
    "add_dialog": "Ctrl+Return",
    "make_dialog_current": "F8",
}

# Human-readable labels for the table
SHORTCUT_LABELS: Dict[str, str] = {
    "toggle_overlay": "Toggle overlay on/off",
    "advance_turn": "Advance turn (next)",
    "previous_turn": "Previous turn",
    "toggle_mode": "Toggle Combat/Dialog mode",
    "focus_search": "Focus active search box",
    "add_dialog": "Add dialog block",
    "make_dialog_current": "Make selected dialog current on overlay",
}


class ShortcutEditorDialog(QtWidgets.QDialog):
    """Dialog to view and change keyboard shortcuts. Saves to config on Apply/OK."""

    def __init__(self, parent: QtWidgets.QWidget, current_shortcuts: Dict[str, str], on_save: Callable[[Dict[str, str]], None]):
        super().__init__(parent)
        self.setWindowTitle("Keyboard Shortcuts")
        self.setMinimumWidth(480)
        self._current = dict(current_shortcuts)
        self._on_save = on_save
        self._editing_key: str | None = None
        self._build_ui()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        self.table = QtWidgets.QTableWidget(len(DEFAULT_SHORTCUTS), 3)
        self.table.setHorizontalHeaderLabels(["Action", "Shortcut", "Change"])
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)

        for row, key in enumerate(DEFAULT_SHORTCUTS):
            action_item = QtWidgets.QTableWidgetItem(SHORTCUT_LABELS.get(key, key))
            action_item.setFlags(action_item.flags() & ~QtCore.Qt.ItemIsEditable)
            self.table.setItem(row, 0, action_item)

            seq = self._current.get(key) or DEFAULT_SHORTCUTS.get(key, "")
            shortcut_item = QtWidgets.QTableWidgetItem(seq)
            shortcut_item.setFlags(shortcut_item.flags() & ~QtCore.Qt.ItemIsEditable)
            shortcut_item.setData(QtCore.Qt.UserRole, key)
            self.table.setItem(row, 1, shortcut_item)

            btn = QtWidgets.QPushButton("Change…")
            btn.setProperty("shortcut_key", key)
            btn.clicked.connect(self._start_capture)
            self.table.setCellWidget(row, 2, btn)

        layout.addWidget(self.table)

        conflict_label = QtWidgets.QLabel("If two actions share the same shortcut, only one will run.")
        conflict_label.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(conflict_label)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel | QtWidgets.QDialogButtonBox.RestoreDefaults
        )
        buttons.accepted.connect(self._apply_and_close)
        buttons.rejected.connect(self.reject)
        restore_btn = buttons.button(QtWidgets.QDialogButtonBox.RestoreDefaults)
        restore_btn.setText("Reset to defaults")
        restore_btn.clicked.disconnect()
        restore_btn.clicked.connect(self._reset_to_defaults)
        layout.addWidget(buttons)

    def _start_capture(self):
        sender = self.sender()
        if isinstance(sender, QtWidgets.QPushButton):
            key = sender.property("shortcut_key")
            if key:
                self._editing_key = key
                row = self._row_for_key(key)
                if row is not None:
                    shortcut_item = self.table.item(row, 1)
                    if shortcut_item:
                        shortcut_item.setText("(press key…)")
                self.setFocus()
                self.grabKeyboard()

    def _row_for_key(self, shortcut_key: str) -> int | None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 1)
            if item and item.data(QtCore.Qt.UserRole) == shortcut_key:
                return row
        return None

    def keyPressEvent(self, event: QtGui.QKeyEvent):
        if self._editing_key is not None:
            self.releaseKeyboard()
            if event.key() == QtCore.Qt.Key_Escape:
                self._refresh_row_for_key(self._editing_key)
                self._editing_key = None
                event.accept()
                return
            key = event.key()
            mods = event.modifiers()
            if key in (QtCore.Qt.Key_Key_unknown, QtCore.Qt.Key_unknown):
                self._refresh_row_for_key(self._editing_key)
                self._editing_key = None
                return
            seq = QtGui.QKeySequence(mods | key)
            seq_str = seq.toString(QtGui.QKeySequence.SequenceFormat.PortableText)
            if not seq_str:
                seq_str = seq.toString()
            self._current[self._editing_key] = seq_str
            self._refresh_row_for_key(self._editing_key)
            self._editing_key = None
            event.accept()
            return
        super().keyPressEvent(event)

    def _refresh_row_for_key(self, shortcut_key: str | None):
        if shortcut_key is None:
            return
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 1)
            if item and item.data(QtCore.Qt.UserRole) == shortcut_key:
                item.setText(self._current.get(shortcut_key) or DEFAULT_SHORTCUTS.get(shortcut_key, ""))
                return

    def _reset_to_defaults(self):
        self._current = dict(DEFAULT_SHORTCUTS)
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 1)
            if item:
                key = item.data(QtCore.Qt.UserRole)
                item.setText(self._current.get(key, ""))

    def _apply_and_close(self):
        self._on_save(self._current)
        self.accept()


def get_shortcuts_from_config(config: dict) -> Dict[str, str]:
    """Merge config shortcuts with defaults. Returns a full key -> sequence map."""
    out = dict(DEFAULT_SHORTCUTS)
    sc = config.get("shortcuts")
    if isinstance(sc, dict):
        for k, v in sc.items():
            if k in DEFAULT_SHORTCUTS and isinstance(v, str) and v.strip():
                out[k] = v.strip()
    return out
