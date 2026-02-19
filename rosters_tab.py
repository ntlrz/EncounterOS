# rosters_tab.py — Packs with Systems + Ranks + Multi-pack selection
from __future__ import annotations
from PySide6 import QtWidgets, QtCore
from pathlib import Path
from typing import Dict, Any, List, Tuple

from app_paths import ROSTERS_DIR
from helpers import (
    safe_json, write_json, collect_suffixes, next_suffix,
    parse_rank, rank_label_for_pack,
)

Pack = Dict[str, Any]

class RostersTab(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QMainWindow):
        super().__init__(parent)
        self.parent = parent
        self._packs: List[Pack] = []           # normalized pack meta
        self._rank_values_sorted: List[Tuple[float, str]] = []  # (numeric, label)
        self._build_ui()
        self._wire()
        self._load_packs()

    # ---------- UI ----------
    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)

        # Filters row
        filter_row = QtWidgets.QHBoxLayout()
        self.cmbSystem = QtWidgets.QComboBox(); self.cmbSystem.setMinimumWidth(160)
        self.cmbSystem.addItem("All Systems", userData=None)
        self.cmbSide   = QtWidgets.QComboBox()
        self.cmbSide.addItems(["Any side","Allies","Opponents"])
        self.cmbMinRank = QtWidgets.QComboBox(); self.cmbMinRank.setMinimumWidth(90)
        self.cmbMaxRank = QtWidgets.QComboBox(); self.cmbMaxRank.setMinimumWidth(90)
        self.edSearch  = QtWidgets.QLineEdit(); self.edSearch.setPlaceholderText("Search name or tag…")

        filter_row.addWidget(QtWidgets.QLabel("System:")); filter_row.addWidget(self.cmbSystem)
        filter_row.addWidget(QtWidgets.QLabel("Side:"));   filter_row.addWidget(self.cmbSide)
        filter_row.addWidget(QtWidgets.QLabel("Min Rank:")); filter_row.addWidget(self.cmbMinRank)
        filter_row.addWidget(QtWidgets.QLabel("Max Rank:")); filter_row.addWidget(self.cmbMaxRank)
        filter_row.addStretch(1)
        filter_row.addWidget(self.edSearch)
        root.addLayout(filter_row)

        # Main split: left packs (multi-select) / right entries
        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)

        # Left: pack list (multi-select)
        left = QtWidgets.QWidget(); vL = QtWidgets.QVBoxLayout(left)
        self.listPacks = QtWidgets.QListWidget()
        self.listPacks.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        vL.addWidget(self.listPacks)

        # Pack actions
        rowL = QtWidgets.QHBoxLayout()
        self.btnSaveParty = QtWidgets.QPushButton("Save Current Party as Roster")
        self.btnDeletePacks = QtWidgets.QPushButton("Delete Selected Roster Files")
        rowL.addWidget(self.btnSaveParty); rowL.addWidget(self.btnDeletePacks); rowL.addStretch(1)
        vL.addLayout(rowL)

        # Right: entries list + add buttons
        right = QtWidgets.QWidget(); vR = QtWidgets.QVBoxLayout(right)
        self.listEntries = QtWidgets.QListWidget()
        self.listEntries.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        vR.addWidget(self.listEntries)

        rowR = QtWidgets.QHBoxLayout()
        self.btnAddSelected = QtWidgets.QPushButton("Add Selected to Combat")
        self.btnAddAll      = QtWidgets.QPushButton("Add All (Filtered)")
        rowR.addStretch(1); rowR.addWidget(self.btnAddSelected); rowR.addWidget(self.btnAddAll)
        vR.addLayout(rowR)

        split.addWidget(left); split.addWidget(right)
        split.setStretchFactor(0, 1); split.setStretchFactor(1, 2)
        root.addWidget(split)

    def _wire(self):
        # packs / filters
        self.listPacks.itemSelectionChanged.connect(self._refresh_entries_view)
        self.cmbSystem.currentIndexChanged.connect(self._refresh_entries_view)
        self.cmbSide.currentIndexChanged.connect(self._refresh_entries_view)
        self.cmbMinRank.currentIndexChanged.connect(self._refresh_entries_view)
        self.cmbMaxRank.currentIndexChanged.connect(self._refresh_entries_view)
        self.edSearch.textChanged.connect(self._refresh_entries_view)
        # actions
        self.btnSaveParty.clicked.connect(self._save_party_as_roster)
        self.btnDeletePacks.clicked.connect(self._delete_selected_packs)
        self.btnAddSelected.clicked.connect(self._add_selected_to_combat)
        self.btnAddAll.clicked.connect(self._add_all_filtered_to_combat)
        self.listEntries.itemDoubleClicked.connect(self._add_one_item)

    # ---------- Load & normalize ----------
    def _load_packs(self):
        self._packs.clear()
        self.listPacks.clear()

        for fp in sorted(ROSTERS_DIR.glob("*.json")):
            data = safe_json(fp, {})
            # Normalize into: {file, name, system, entries: [members], rank_label}
            name = data.get("name") or fp.stem
            system = (data.get("system") or "").strip() or None
            entries = self._extract_entries(data)
            rank_label = rank_label_for_pack(system, None)  # “CR”, “Level”, etc. from helpers.py :contentReference[oaicite:9]{index=9}

            pack = {
                "file": fp, "name": name, "system": system,
                "entries": entries, "rank_label": rank_label
            }
            self._packs.append(pack)

            # show system and count
            suffix = f" [{system}]" if system else ""
            it = QtWidgets.QListWidgetItem(f"{name}{suffix} — {len(entries)}")
            it.setData(QtCore.Qt.UserRole, pack)
            self.listPacks.addItem(it)

        # Build system filter options from what we found
        systems = sorted({p["system"] for p in self._packs if p["system"]})
        for s in systems:
            self.cmbSystem.addItem(s, userData=s)

        # Build rank options (global) from all packs
        ranks = []
        for p in self._packs:
            for m in p["entries"]:
                v, txt = parse_rank(m.get("rank"))
                ranks.append((v, txt))
        uniq = {}
        for v, txt in ranks:
            # keep first text we saw for this numeric value
            if v not in uniq:
                uniq[v] = txt
        self._rank_values_sorted = sorted(((v, uniq[v]) for v in uniq.keys()), key=lambda x: x[0])

        def _fill_rank_combo(cmb: QtWidgets.QComboBox):
            cmb.clear()
            cmb.addItem("Any", userData=None)
            for v, txt in self._rank_values_sorted:
                cmb.addItem(txt, userData=v)

        _fill_rank_combo(self.cmbMinRank)
        _fill_rank_combo(self.cmbMaxRank)
        self.cmbMinRank.setCurrentIndex(0)
        self.cmbMaxRank.setCurrentIndex(0)

        # Initial fill on right
        self._refresh_entries_view()

    def _extract_entries(self, data: Any) -> List[Dict]:
        """Accept many schemas:
           - App native: {"roster":[...] }
           - Common: {"characters"| "creatures"| "monsters": [...]}
           - Pack style: {"entries":[...]}  <-- your SRD/Draw Steel packs
           - Raw list: [ ... ]
        """
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("roster", "characters", "creatures", "monsters", "entries"):
                val = data.get(key)
                if isinstance(val, list):
                    return val
        return []

    # ---------- View build ----------
    def _refresh_entries_view(self):
        # Collect selected packs
        selected_packs = [it.data(QtCore.Qt.UserRole) for it in self.listPacks.selectedItems()] or self._packs

        # Filters
        want_system = self.cmbSystem.currentData()
        side_mode = self.cmbSide.currentText()
        min_rank = self.cmbMinRank.currentData()
        max_rank = self.cmbMaxRank.currentData()
        query = (self.edSearch.text() or "").strip().lower()

        # Aggregate, filter, and show entries
        self.listEntries.clear()
        for pack in selected_packs:
            if want_system and pack["system"] != want_system:
                continue
            rlabel = pack["rank_label"]
            for m in pack["entries"]:
                # side filter
                side = (m.get("side_default") or "").lower()
                if side_mode == "Allies" and side != "allies":
                    continue
                if side_mode == "Opponents" and side != "opponents":
                    continue
                # rank filter
                v, txt = parse_rank(m.get("rank"))  # numeric + original text (e.g., “1/8”) :contentReference[oaicite:10]{index=10}
                if min_rank is not None and v < float(min_rank): continue
                if max_rank is not None and v > float(max_rank): continue
                # search filter (name or tags)
                hay = " ".join([m.get("name",""), " ".join(m.get("tags") or [])]).lower()
                if query and query not in hay:
                    continue

                # Show as: Name — RankLabel: X — [Allies/Opponents]
                name = m.get("name","Unknown")
                side_tag = "Allies" if side == "allies" else ("Opponents" if side == "opponents" else "Neutral")
                label = f"{name} — {rlabel}: {txt or '0'} — {side_tag}"
                it = QtWidgets.QListWidgetItem(label)
                it.setData(QtCore.Qt.UserRole, (m, pack))
                self.listEntries.addItem(it)

    # ---------- Normalize & add ----------
    def _normalize_member(self, m: Dict, pack: Pack) -> Dict:
        """Map various pack fields into the CombatTab model."""
        # HP/Stamina
        hp = m.get("hp")
        if hp is None:
            hp = m.get("stamina", 1)  # Draw Steel uses 'stamina' :contentReference[oaicite:11]{index=11}
        hp = max(1, int(hp))
        # Init mod variants
        init_mod = m.get("initMod", m.get("init_mod", 0))
        # Side -> isPC
        side = (m.get("side_default") or "").lower()
        is_pc = (side == "allies")

        out = {
            "name": m.get("name", "Creature"),
            "hp": hp,
            "hpMax": hp,
            "initMod": int(init_mod or 0),
            "initTotal": None,
            "statuses": [],
            "portrait": m.get("icon") or None,
            "isPC": is_pc,
            # You can carry through pack/system/rank tags if useful later:
            "rank": m.get("rank"),
            "tags": list(m.get("tags") or []),
            "system": pack.get("system"),
        }
        return out

    def _uniqueize_batch(self, members: List[Dict]) -> List[Dict]:
        existing = [x.get("name","") for x in self.parent.combat_tab.combatants]
        uniq = []
        for i, m in enumerate(members):
            base = (m.get("name") or "Creature").split(" (")[0]
            taken = collect_suffixes(base, existing + [x.get("name","") for x in uniq])
            mm = dict(m)
            if "" in taken:  # already a bare duplicate name, add a suffix
                mm["name"] = f"{base} ({next_suffix(taken)})"
            uniq.append(mm)
        return uniq

    def _add_payload(self, items: List[QtWidgets.QListWidgetItem]):
        if not items:
            return
        payload = []
        for it in items:
            m, pack = it.data(QtCore.Qt.UserRole)
            payload.append(self._normalize_member(m, pack))
        payload = self._uniqueize_batch(payload)
        # Push into Combat and persist/refresh (your CombatTab API) :contentReference[oaicite:12]{index=12}
        self.parent.combat_tab.combatants.extend(payload)
        self.parent.combat_tab._refresh_combat_list()
        self.parent.combat_tab._persist_party()

    # Actions
    def _add_selected_to_combat(self):
        items = self.listEntries.selectedItems()
        if not items:
            QtWidgets.QMessageBox.information(self, "Rosters", "Select one or more entries first.")
            return
        self._add_payload(items)

    def _add_all_filtered_to_combat(self):
        n = self.listEntries.count()
        items = [self.listEntries.item(i) for i in range(n)]
        if not items:
            return
        self._add_payload(items)

    def _add_one_item(self, it: QtWidgets.QListWidgetItem):
        self._add_payload([it])

    # Save/Delete roster files
    def _save_party_as_roster(self):
        name, ok = QtWidgets.QInputDialog.getText(self, "Save Roster", "Roster file name:")
        if not ok or not name:
            return
        members = self.parent.combat_tab.combatants
        if not members:
            QtWidgets.QMessageBox.warning(self, "Empty Party", "Cannot save an empty party.")
            return
        fp = ROSTERS_DIR / f"{name.strip()}.json"
        write_json(fp, {"roster": members})
        self.parent._log(f"Saved roster: {fp.name}")
        self._load_packs()

    def _delete_selected_packs(self):
        rows = self.listPacks.selectedItems()
        if not rows:
            return
        if QtWidgets.QMessageBox.question(self, "Delete Roster Files",
                                          "Delete selected roster files?",
                                          QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No) != QtWidgets.QMessageBox.Yes:
            return
        for it in rows:
            pack = it.data(QtCore.Qt.UserRole)
            fp: Path = pack["file"]
            if fp.exists():
                fp.unlink()
                self.parent._log(f"Deleted roster file: {fp.name}")
        self._load_packs()
