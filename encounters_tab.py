from __future__ import annotations
from PySide6 import QtWidgets, QtCore, QtGui
from pathlib import Path
import json

from app_paths import DATA_ROOT, COMBAT_DIR, DIALOG_DIR
from helpers import safe_json, write_json

class EncountersTab(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QMainWindow):
        super().__init__()
        self.parent = parent
        self._build_ui()
        self._load_encounter_list()

    def _build_ui(self):
        v_layout = QtWidgets.QVBoxLayout(self)
        
        h_buttons = QtWidgets.QHBoxLayout()
        self.btnSaveCombat = QtWidgets.QPushButton("Save Current Combat")
        self.btnSaveDialog = QtWidgets.QPushButton("Save Current Dialog")
        h_buttons.addWidget(self.btnSaveCombat)
        h_buttons.addWidget(self.btnSaveDialog)
        v_layout.addLayout(h_buttons)
        
        self.listEncounters = QtWidgets.QListWidget()
        v_layout.addWidget(self.listEncounters)
        
        h_actions = QtWidgets.QHBoxLayout()
        self.btnLoad = QtWidgets.QPushButton("Load")
        self.btnDelete = QtWidgets.QPushButton("Delete")
        h_actions.addWidget(self.btnLoad)
        h_actions.addWidget(self.btnDelete)
        v_layout.addLayout(h_actions)

        self.btnSaveCombat.clicked.connect(self._save_combat)
        self.btnSaveDialog.clicked.connect(self._save_dialog)
        self.btnLoad.clicked.connect(self._load_encounter)
        self.btnDelete.clicked.connect(self._delete_encounter)
        self.listEncounters.itemDoubleClicked.connect(self._load_encounter)

    def _load_encounter_list(self):
        self.listEncounters.clear()
        
        encounters = []
        for fp in sorted(COMBAT_DIR.glob("*.json")):
            encounters.append(f"[Combat] {fp.stem}")
            
        for fp in sorted(DIALOG_DIR.glob("*.json")):
            encounters.append(f"[Dialog] {fp.stem}")
            
        self.listEncounters.addItems(encounters)

    def _save_combat(self):
        name, ok = QtWidgets.QInputDialog.getText(self, "Save Encounter", "Enter name for combat encounter:")
        if not ok or not name: return
        
        payload = {
            "party": self.parent.combat_tab.combatants,
            "turn_index": self.parent.combat_tab.turn_index,
            "round": self.parent.combat_tab.round,
        }
        
        fp = COMBAT_DIR / f"{name.strip()}.json"
        write_json(fp, payload)
        self.parent._log(f"Saved combat encounter: {fp.name}")
        self._load_encounter_list()
        
    def _save_dialog(self):
        name, ok = QtWidgets.QInputDialog.getText(self, "Save Encounter", "Enter name for dialog encounter:")
        if not ok or not name: return
        
        payload = {
            "dialog": self.parent.dialog_tab.dialog_blocks,
            "dialog_index": self.parent.dialog_tab.dialog_index,
        }
        
        fp = DIALOG_DIR / f"{name.strip()}.json"
        write_json(fp, payload)
        self.parent._log(f"Saved dialog encounter: {fp.name}")
        self._load_encounter_list()

    def _load_encounter(self):
        selected = self.listEncounters.currentItem()
        if not selected: return
        
        name = selected.text()
        parts = name.split(" ")
        enc_type = parts[0][1:-1]
        enc_name = " ".join(parts[1:])
        
        if enc_type == "Combat":
            fp = COMBAT_DIR / f"{enc_name}.json"
            if fp.exists():
                data = safe_json(fp, {})
                self.parent.combat_tab.combatants = data.get("party", [])
                self.parent.combat_tab.turn_index = data.get("turn_index", -1)
                self.parent.combat_tab.round = data.get("round", 1)
                self.parent.combat_tab._refresh_combat_list()
                self.parent._log(f"Loaded combat encounter: {enc_name}")
        elif enc_type == "Dialog":
            fp = DIALOG_DIR / f"{enc_name}.json"
            if fp.exists():
                data = safe_json(fp, {})
                self.parent.dialog_tab.dialog_blocks = data.get("dialog", [])
                self.parent.dialog_tab.dialog_index = data.get("dialog_index", -1)
                self.parent.dialog_tab._refresh_dialog_list()
                self.parent._log(f"Loaded dialog encounter: {enc_name}")

    def _delete_encounter(self):
        selected = self.listEncounters.currentItem()
        if not selected: return

        name = selected.text()
        parts = name.split(" ")
        enc_type = parts[0][1:-1]
        enc_name = " ".join(parts[1:])
        
        reply = QtWidgets.QMessageBox.question(self, 'Delete Encounter', 
                                                f"Are you sure you want to delete '{enc_name}'?",
                                                QtWidgets.QMessageBox.Yes, QtWidgets.QMessageBox.No)
        if reply == QtWidgets.QMessageBox.No:
            return

        if enc_type == "Combat":
            fp = COMBAT_DIR / f"{enc_name}.json"
            if fp.exists():
                fp.unlink()
                self.parent._log(f"Deleted combat encounter: {enc_name}")
        elif enc_type == "Dialog":
            fp = DIALOG_DIR / f"{enc_name}.json"
            if fp.exists():
                fp.unlink()
                self.parent._log(f"Deleted dialog encounter: {enc_name}")
        
        self._load_encounter_list()