from __future__ import annotations
from PySide6 import QtWidgets, QtGui, QtCore
from typing import Dict, List, Any
import json
from pathlib import Path

from helpers import roll_d20, now_iso, write_json, collect_suffixes, next_suffix
from app_paths import PARTY_FP, LOG_FILE, ROSTERS_DIR, SESSION_ROSTER_FP

class CombatTab(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QMainWindow):
        super().__init__()
        self.parent = parent
        self.combatants: List[Dict] = []
        self.turn_index: int = -1
        self.round: int = 1
        
        self._build_ui()
        self._wire_signals()
        
        self._load_party()

    def _build_ui(self):
        v_layout = QtWidgets.QVBoxLayout(self)
        
        # Search & Add Section
        h_search = QtWidgets.QHBoxLayout()
        self.searchCombat = QtWidgets.QLineEdit()
        self.searchCombat.setPlaceholderText("Quick Add: Goblin")
        self.searchCombat.returnPressed.connect(self._add_from_search)  # Enter key support
        btn_add = QtWidgets.QPushButton("Add")
        btn_add.clicked.connect(self._add_from_search)
        self.spin_add = QtWidgets.QSpinBox()
        self.spin_add.setRange(1, 99)
        self.spin_add.setValue(1)
        btn_create = QtWidgets.QPushButton("Create Character…")
        btn_create.clicked.connect(self._create_character)
        h_search.addWidget(self.searchCombat)
        h_search.addWidget(btn_add)
        h_search.addWidget(QtWidgets.QLabel("x"))
        h_search.addWidget(self.spin_add)
        h_search.addWidget(btn_create)
        v_layout.addLayout(h_search)

        # Initiative & HP tools
        h_tools = QtWidgets.QHBoxLayout()
        self.btnRollInit = QtWidgets.QPushButton("Roll Init (All)")
        self.btnSortInit = QtWidgets.QPushButton("Sort by Init")
        self.btnHPm5 = QtWidgets.QPushButton("HP -5")
        self.btnHPm1 = QtWidgets.QPushButton("HP -1")
        self.btnHPp1 = QtWidgets.QPushButton("HP +1")
        self.btnHPp5 = QtWidgets.QPushButton("HP +5")
        self.btnStatuses = QtWidgets.QPushButton("Statuses…")
        h_tools.addWidget(self.btnRollInit)
        h_tools.addWidget(self.btnSortInit)
        h_tools.addStretch(1)
        h_tools.addWidget(self.btnHPm5)
        h_tools.addWidget(self.btnHPm1)
        h_tools.addWidget(self.btnHPp1)
        h_tools.addWidget(self.btnHPp5)
        h_tools.addWidget(self.btnStatuses)
        v_layout.addLayout(h_tools)
        
        # Combat List
        self.listCombat = QtWidgets.QListWidget()
        self.listCombat.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.listCombat.setAlternatingRowColors(True)
        self.listCombat.setUniformItemSizes(True)
        v_layout.addWidget(self.listCombat)
        
        # Combatant Actions
        h_actions = QtWidgets.QHBoxLayout()
        self.btnEdit = QtWidgets.QPushButton("Edit")
        self.btnRemove = QtWidgets.QPushButton("Remove")
        self.btnDuplicate = QtWidgets.QPushButton("Duplicate")
        self.btnClear = QtWidgets.QPushButton("Clear All")
        h_actions.addWidget(self.btnEdit)
        h_actions.addWidget(self.btnRemove)
        h_actions.addWidget(self.btnDuplicate)
        h_actions.addWidget(self.btnClear)
        v_layout.addLayout(h_actions)

        # Roster Actions
        h_rosters = QtWidgets.QHBoxLayout()
        h_rosters.addWidget(QtWidgets.QLabel("Rosters:"))
        self.comboRosters = QtWidgets.QComboBox()
        self._populate_rosters()
        btn_load = QtWidgets.QPushButton("Load")
        btn_save = QtWidgets.QPushButton("Save")
        btn_session_load = QtWidgets.QPushButton("Load Session")
        btn_session_load.setToolTip("Load the auto-saved session roster")
        btn_session_save = QtWidgets.QPushButton("Save Session")
        btn_session_save.setToolTip("Save current party as session roster (auto-saved)")
        h_rosters.addWidget(self.comboRosters)
        h_rosters.addWidget(btn_load)
        h_rosters.addWidget(btn_save)
        h_rosters.addWidget(QtWidgets.QLabel("|"))
        h_rosters.addWidget(btn_session_load)
        h_rosters.addWidget(btn_session_save)
        btn_load.clicked.connect(self._load_roster)
        btn_save.clicked.connect(self._save_roster)
        btn_session_load.clicked.connect(self._load_session_roster)
        btn_session_save.clicked.connect(self._save_session_roster)
        v_layout.addLayout(h_rosters)
        
        # Controls & Info
        h_ctrls = QtWidgets.QHBoxLayout()
        self.lblTurn = QtWidgets.QLabel("Turn: - / -")
        self.btnPrev = QtWidgets.QPushButton("◄ Previous")
        self.btnPrev.setMinimumWidth(100)
        self.btnPrev.setProperty("class", "primary")
        self.btnNext = QtWidgets.QPushButton("Next ►")
        self.btnNext.setMinimumWidth(100)
        self.btnNext.setProperty("class", "primary")
        h_ctrls.addWidget(self.lblTurn)
        h_ctrls.addStretch(1)
        h_ctrls.addWidget(self.btnPrev)
        h_ctrls.addWidget(self.btnNext)
        v_layout.addLayout(h_ctrls)

    def _wire_signals(self):
        self.btnEdit.clicked.connect(self._edit_selected)
        self.btnRemove.clicked.connect(self._remove_selected)
        self.btnDuplicate.clicked.connect(self._duplicate_selected)
        self.btnClear.clicked.connect(self._clear_combat)
        self.btnNext.clicked.connect(self._advance_combat_next)
        self.btnPrev.clicked.connect(self._advance_combat_prev)
        self.listCombat.itemSelectionChanged.connect(self._on_combat_selection_changed)
        self.btnRollInit.clicked.connect(self._roll_initiative_all)
        self.btnSortInit.clicked.connect(self._sort_by_initiative)
        self.btnHPm5.clicked.connect(lambda: self._adjust_hp_selected(-5))
        self.btnHPm1.clicked.connect(lambda: self._adjust_hp_selected(-1))
        self.btnHPp1.clicked.connect(lambda: self._adjust_hp_selected(+1))
        self.btnHPp5.clicked.connect(lambda: self._adjust_hp_selected(+5))
        self.btnStatuses.clicked.connect(self._edit_statuses_selected)

    def _add_from_search(self):
        name = self.searchCombat.text().strip()
        count = self.spin_add.value()
        if not name or not count:
            return
        
        # Better defaults: use reasonable HP based on common creature types
        # You can always edit them after adding
        default_hp = 10  # Reasonable default for most creatures
        if any(word in name.lower() for word in ["goblin", "kobold", "skeleton"]):
            default_hp = 7
        elif any(word in name.lower() for word in ["dragon", "giant", "troll"]):
            default_hp = 50
        
        for i in range(count):
            display_name = name if count == 1 else f"{name} ({chr(65+i)})"
            self.combatants.append({
                "name": display_name,
                "hp": default_hp,
                "hpMax": default_hp,
                "initMod": 0,
                "initTotal": None,
                "notes": "",
                "statuses": [],
                "portrait": None,
                "side": "Enemy",
                "isPC": False,
            })
        
        self._refresh_combat_list()
        self._persist_party()
        self.parent._log(f"Added {count} x '{name}' from search.")
        self.searchCombat.clear()
    
    def _create_character(self):
        """Open character creation dialog with sensible defaults."""
        from gm_window import EntityDialog
        # Default to a friendly character with reasonable HP
        default_data = {
            "name": "New Character",
            "hp": 20,
            "hpMax": 20,
            "initMod": 0,
            "initTotal": None,
            "notes": "",
            "statuses": [],
            "portrait": None,
            "side": "Friendly",
            "isPC": True,
        }
        d = EntityDialog(self.parent, data=default_data)
        if d.exec():
            payload = d.payload()
            self.combatants.append(payload)
            self._refresh_combat_list()
            self._persist_party()
            self.parent._log(f"Created character: {payload['name']}")

    def _edit_selected(self):
        rows = self.listCombat.selectedIndexes()
        if not rows: return
        idx = rows[0].row()
        if not (0 <= idx < len(self.combatants)): return
        
        data = self.combatants[idx]
        # EntityDialog is defined in gm_window.py, access via parent
        from gm_window import EntityDialog
        d = EntityDialog(self.parent, data=data)
        if d.exec():
            payload = d.payload()
            self.combatants[idx] = payload
            self._refresh_combat_list()
            self._persist_party()
            self.parent._log(f"Edited combatant: {payload['name']}")
    
    def _remove_selected(self):
        rows = sorted([i.row() for i in self.listCombat.selectedIndexes()], reverse=True)
        if not rows: return
        
        removed_names = []
        for r in rows:
            if 0 <= r < len(self.combatants):
                removed_names.append(self.combatants.pop(r)["name"])
        
        self.turn_index = min(self.turn_index, len(self.combatants) - 1)
        if self.turn_index < 0 and self.combatants:
            self.turn_index = 0
            
        self._refresh_combat_list()
        self._persist_party()
        self.parent._log(f"Removed combatants: {', '.join(removed_names)}")

    def _duplicate_selected(self):
        rows = sorted([i.row() for i in self.listCombat.selectedIndexes()])
        if not rows: return
        
        new_items = []
        for r in rows:
            if 0 <= r < len(self.combatants):
                original = self.combatants[r]
                new_item = json.loads(json.dumps(original))
                
                all_names = [m.get("name") for m in self.combatants]
                base_name = original.get("name").split(" (")[0]
                suffixes = collect_suffixes(base_name, all_names)
                suffix = next_suffix(suffixes)
                
                new_item["name"] = f"{base_name} ({suffix})"
                new_items.append(new_item)
        
        self.combatants.extend(new_items)
        self._refresh_combat_list()
        self._persist_party()
        self.parent._log(f"Duplicated {len(new_items)} combatants.")

    def _clear_combat(self):
        msg = QtWidgets.QMessageBox()
        msg.setIcon(QtWidgets.QMessageBox.Warning)
        msg.setWindowTitle("Clear Combat?")
        msg.setText("Are you sure you want to clear all combatants?")
        msg.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        if msg.exec() == QtWidgets.QMessageBox.Yes:
            self.combatants = []
            self.turn_index = -1
            self.round = 1
            self._refresh_combat_list()
            self._persist_party()
            self.parent._log("Combatants cleared.")

    def _refresh_combat_list(self):
        self.listCombat.clear()
        for i, m in enumerate(self.combatants):
            self._update_combat_row(i)
        self._update_combat_hud()
        
    def _update_combat_row(self, i: int):
        if not (0 <= i < len(self.combatants)): return
        m = self.combatants[i]
        hp_cur = m.get("hp", "—")
        hp_max = m.get("hpMax", "?")
        hp_text = f"{hp_cur}/{hp_max}" if hp_max is not None else str(hp_cur)
        text = f"{i+1}. {m.get('name', '???')} ({hp_text} hp) [Init: {m.get('initTotal', '—')}]"
        
        if i < self.listCombat.count():
            item = self.listCombat.item(i)
        else:
            item = QtWidgets.QListWidgetItem()
            self.listCombat.addItem(item)
            
        item.setText(text)
        item.setToolTip(json.dumps(m, indent=2))
        
        if i == self.turn_index:
            item.setBackground(QtGui.QBrush(QtGui.QColor("#404040") if self.parent.ui_dark else QtGui.QColor("#C0C0C0")))
            item.setForeground(QtGui.QBrush(QtGui.QColor("#FFD700")))
        else:
            item.setBackground(QtGui.QBrush(QtGui.QColor("transparent")))
            item.setForeground(QtGui.QBrush(QtGui.QColor("#e6e6e6") if self.parent.ui_dark else QtGui.QColor("#101010")))
            
    def _update_combat_hud(self):
        total = len(self.combatants)
        name = self.combatants[self.turn_index]["name"] if (0 <= self.turn_index < total) else "—"
        self.lblTurn.setText(f"Round {self.round} • Turn: {name}")

    def _persist_party(self):
        write_json(PARTY_FP, {"party": self.combatants, "turn_index": self.turn_index, "round": self.round})
        # Auto-save to session roster whenever party changes
        if self.combatants:
            write_json(SESSION_ROSTER_FP, {
                "roster": self.combatants,
                "turn_index": self.turn_index,
                "round": self.round,
            })
        
    def _load_party(self):
        try:
            with open(PARTY_FP, "r") as f:
                data = json.load(f)
                self.combatants = data.get("party", [])
                self.turn_index = data.get("turn_index", -1)
                self.round = data.get("round", 1)
        except (FileNotFoundError, json.JSONDecodeError):
            self.combatants = []
            self.turn_index = -1
            self.round = 1
        
        self._refresh_combat_list()
        self.parent._log("Combatants loaded from file.")
        
    def _advance_combat_next(self):
        if not self.combatants: return
        
        if self.turn_index == len(self.combatants) - 1:
            self.turn_index = 0
            self.round += 1
        else:
            self.turn_index += 1
            
        self._refresh_combat_list()
        self._persist_party()

    def _advance_combat_prev(self):
        if not self.combatants: return
        
        if self.turn_index == 0:
            if self.round > 1:
                self.turn_index = len(self.combatants) - 1
                self.round -= 1
            else:
                return
        else:
            self.turn_index -= 1
            
        self._refresh_combat_list()
        self._persist_party()

    def _populate_rosters(self):
        self.comboRosters.clear()
        self.comboRosters.addItem("—")
        for f in sorted(ROSTERS_DIR.glob("*.json")):
            if f.name != "_session.json":  # Don't show session roster in regular list
                self.comboRosters.addItem(f.stem)
    
    def _load_roster(self):
        """Load a selected roster from the combo box."""
        name = self.comboRosters.currentText()
        if name == "—" or not name:
            return
        fp = ROSTERS_DIR / f"{name}.json"
        if not fp.exists():
            self.parent._log(f"Roster file not found: {name}")
            return
        try:
            import json
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
            members = data.get("roster", data.get("entries", []))
            if not isinstance(members, list):
                members = []
            self.combatants = members
            self.turn_index = -1
            self.round = 1
            self._refresh_combat_list()
            self._persist_party()
            self.parent._log(f"Loaded roster: {name} ({len(members)} members)")
        except Exception as e:
            self.parent._log(f"Error loading roster: {e}")
    
    def _save_roster(self):
        """Save current party as a named roster."""
        name, ok = QtWidgets.QInputDialog.getText(self, "Save Roster", "Roster file name:")
        if not ok or not name:
            return
        if not self.combatants:
            QtWidgets.QMessageBox.warning(self, "Empty Party", "Cannot save an empty party.")
            return
        fp = ROSTERS_DIR / f"{name.strip()}.json"
        write_json(fp, {"roster": self.combatants})
        self.parent._log(f"Saved roster: {fp.name}")
        self._populate_rosters()
    
    def _load_session_roster(self):
        """Load the auto-saved session roster."""
        if not SESSION_ROSTER_FP.exists():
            QtWidgets.QMessageBox.information(self, "No Session", "No saved session roster found.")
            return
        try:
            import json
            with open(SESSION_ROSTER_FP, "r", encoding="utf-8") as f:
                data = json.load(f)
            members = data.get("roster", data.get("entries", []))
            if not isinstance(members, list):
                members = []
            self.combatants = members
            self.turn_index = data.get("turn_index", -1)
            self.round = data.get("round", 1)
            self._refresh_combat_list()
            self._persist_party()
            self.parent._log(f"Loaded session roster ({len(members)} members)")
        except Exception as e:
            self.parent._log(f"Error loading session roster: {e}")
    
    def _save_session_roster(self):
        """Save current party as session roster (auto-saved)."""
        if not self.combatants:
            QtWidgets.QMessageBox.information(self, "Empty Party", "No combatants to save.")
            return
        write_json(SESSION_ROSTER_FP, {
            "roster": self.combatants,
            "turn_index": self.turn_index,
            "round": self.round,
        })
        self.parent._log(f"Saved session roster ({len(self.combatants)} members)")
            
    def _on_combat_selection_changed(self):
        # Notify the parent window so it can update its display (if needed)
        pass

    def _roll_initiative_all(self):
        # initTotal = d20 + initMod, keep initMod
        for m in self.combatants:
            mod = int(m.get("initMod") or 0)
            roll = roll_d20()
            m["initRoll"] = roll
            m["initTotal"] = roll + mod
        self.parent._log("Rolled initiative for all.")
        self._sort_by_initiative()

    def _sort_by_initiative(self):
        self.combatants.sort(
            key=lambda m: (m.get("initTotal") is None, -(m.get("initTotal") or 0), m.get("name","").lower())
        )
        # reset turn index to top if empty/invalid
        if not (0 <= self.turn_index < len(self.combatants)):
            self.turn_index = 0 if self.combatants else -1
        self._refresh_combat_list()
        self._persist_party()
        self.parent._log("Sorted by initiative.")

    def _adjust_hp_selected(self, delta: int):
        rows = [i.row() for i in self.listCombat.selectedIndexes()]
        if not rows: return
        changed = []
        for r in rows:
            if 0 <= r < len(self.combatants):
                m = self.combatants[r]
                hp = int(m.get("hp") or 0)
                mx = max(1, int(m.get("hpMax") or 1))
                m["hp"] = max(0, min(hp + delta, mx))
                changed.append(m.get("name","?"))
        self._refresh_combat_list()
        self._persist_party()
        if changed:
            self.parent._log(f"Adjusted HP for: {', '.join(changed)} ({delta:+})")

    def _edit_statuses_selected(self):
        rows = self.listCombat.selectedIndexes()
        if not rows: return
        idx = rows[0].row()
        if not (0 <= idx < len(self.combatants)): return
        m = self.combatants[idx]
        cur = list(m.get("statuses") or [])
        dlg = self.parent._StatusEditorDialog(self.parent, cur, self.parent._status_catalog)
        if dlg.exec():
            m["statuses"] = dlg.payload()
            self._refresh_combat_list()
            self._persist_party()
            self.parent._log(f"Updated statuses: {m.get('name','?')}")