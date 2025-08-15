from __future__ import annotations

import json, random, subprocess, sys, os, shutil
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton, QListWidget, QListWidgetItem,
    QLineEdit, QSpinBox, QDoubleSpinBox, QCheckBox, QFileDialog, QMessageBox, QGridLayout, QHBoxLayout,
    QVBoxLayout, QGroupBox, QTableWidget, QTableWidgetItem, QHeaderView, QDialog, QDialogButtonBox,
    QComboBox, QPlainTextEdit, QSplitter
)

# =========================
# Paths & constants
# =========================
APP_DIR       = Path(__file__).resolve().parent
PARTY_FILE    = APP_DIR / "party.json"
CONFIG_FILE   = APP_DIR / "config.json"
DIALOG_FILE   = APP_DIR / "dialog.txt"
DIALOG_META   = APP_DIR / "dialog_meta.json"      # NEW: per-block portrait + offsets
ICONS_DIR     = APP_DIR / "icons"
STATUS_DIR    = ICONS_DIR / "status"
PORTRAITS_DIR = ICONS_DIR / "dialog_portraits"    # NEW: we copy chosen portraits here
THEMES_DIR    = APP_DIR / "themes"
OVERLAY_PY    = APP_DIR / "tracker_overlay.py"

ICON_SIZE     = (64, 64)
STATUS_KEYS   = [
    "poisoned","stunned","prone","concentrating","blessed","hexed","frightened","invisible",
    "grappled","restrained","paralyzed","petrified","deafened","blinded","baned"
]
STATUS_EMOJI  = {"poisoned":"☠️","stunned":"💫","prone":"🛏️","concentrating":"🎯","blessed":"✨",
                 "hexed":"🪄","frightened":"😱","invisible":"👻","grappled":"🤼","restrained":"⛓️",
                 "paralyzed":"🧊","petrified":"🗿","deafened":"🔕","blinded":"🙈","baned":"⛔"}

# =========================
# GM UI Light/Dark only (GM window — overlay theming is separate)
# =========================
def apply_gm_ui_qss(mode: str):
    if mode == "dark":
        qss = """
        QMainWindow, QWidget { background: #1e1e1e; color: #eaeaea; }
        QGroupBox { border: 1px solid #444; margin-top: 10px; }
        QGroupBox::title { subcontrol-origin: margin; left: 8px; top: -7px; padding: 0 4px; background: #1e1e1e; }
        QPushButton { background: #2b2b2b; border: 1px solid #555; padding: 4px 8px; }
        QPushButton:hover { background: #333; }
        QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit { background: #2b2b2b; border: 1px solid #555; }
        QListWidget, QTableWidget { background: #232323; border: 1px solid #444; }
        """
    else:
        qss = """
        QMainWindow, QWidget { background: #fafafa; color: #111; }
        QGroupBox { border: 1px solid #bbb; margin-top: 10px; }
        QGroupBox::title { subcontrol-origin: margin; left: 8px; top: -7px; padding: 0 4px; background: #fafafa; }
        QPushButton { background: #fff; border: 1px solid #bbb; padding: 4px 8px; }
        QPushButton:hover { background: #f0f0f0; }
        QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit { background: #fff; border: 1px solid #bbb; }
        QListWidget, QTableWidget { background: #fff; border: 1px solid #bbb; }
        """
    QApplication.instance().setStyleSheet(qss)

# =========================
# Model & store
# =========================
@dataclass
class PartyMember:
    name: str
    maxHP: int
    currentHP: int
    isEnemy: bool
    turnOrder: int = 0
    icon: str = ""
    statusEffects: List[str] = None
    initMod: int = 0
    initiative: Optional[int] = None
    active: bool = False

    @staticmethod
    def from_dict(d: Dict) -> "PartyMember":
        return PartyMember(
            name=d.get("name",""),
            maxHP=int(d.get("maxHP",0)),
            currentHP=int(d.get("currentHP",0)),
            isEnemy=bool(d.get("isEnemy",False)),
            turnOrder=int(d.get("turnOrder",0)),
            icon=d.get("icon",""),
            statusEffects=list(d.get("statusEffects",[]) or []),
            initMod=int(d.get("initMod",0)),
            initiative=d.get("initiative",None),
            active=bool(d.get("active", False)),
        )
    def to_dict(self)->Dict: return asdict(self)

class PartyStore:
    def __init__(self):
        ICONS_DIR.mkdir(parents=True, exist_ok=True)
        STATUS_DIR.mkdir(parents=True, exist_ok=True)
        PORTRAITS_DIR.mkdir(parents=True, exist_ok=True)
        if not PARTY_FILE.exists(): PARTY_FILE.write_text(json.dumps({"party":[]}, indent=2), encoding="utf-8")
        if not CONFIG_FILE.exists(): CONFIG_FILE.write_text(json.dumps({"combat_mode":False,"turnIndex":0,"dialogIndex":0,"theme":"gm-modern"}, indent=2), encoding="utf-8")
        if not DIALOG_FILE.exists(): DIALOG_FILE.write_text("Speaker: Hello world.\n\nNarrator: This is a sample block.\n", encoding="utf-8")
        if not DIALOG_META.exists(): DIALOG_META.write_text("{}", encoding="utf-8")
        self.party: List[PartyMember] = self.load_party()
        self.config: Dict = self.load_config()
        self.dialog_meta: Dict = self.load_dialog_meta()

    def load_party(self)->List[PartyMember]:
        try:
            data=json.loads(PARTY_FILE.read_text(encoding="utf-8"))
            return [PartyMember.from_dict(x) for x in data.get("party",[])]
        except: return []

    def save_party(self):
        PARTY_FILE.write_text(json.dumps({"party":[m.to_dict() for m in self.party]}, indent=2), encoding="utf-8")

    def load_config(self)->Dict:
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except:
            cfg = {"combat_mode":False,"turnIndex":0,"dialogIndex":0,"theme":"gm-modern"}
        if "theme" not in cfg:
            cfg["theme"] = "gm-modern"
        return cfg

    def save_config(self):
        if "theme" not in self.config:
            self.config["theme"] = "gm-modern"
        CONFIG_FILE.write_text(json.dumps(self.config, indent=2), encoding="utf-8")

    def load_dialog_meta(self)->Dict:
        try:
            return json.loads(DIALOG_META.read_text(encoding="utf-8"))
        except:
            return {}

    def save_dialog_meta(self):
        DIALOG_META.write_text(json.dumps(self.dialog_meta, indent=2), encoding="utf-8")

    def sort_by_initiative(self):
        actives = [m for m in self.party if m.active]
        actives.sort(key=lambda m:(m.initiative or 0, m.name.lower()), reverse=True)
        order = 1
        for m in self.party:
            if m.active:
                m.turnOrder = order; order += 1
            else:
                m.turnOrder = 0
        self.save_party()

# =========================
# Helpers
# =========================
def process_icon_to_gray(src: Path, name_for_file: str) -> str:
    try:
        img = Image.open(src).convert("L").resize(ICON_SIZE)
        img = Image.eval(img, lambda px: int(px*0.7)+60)
        out = ICONS_DIR / f"{name_for_file.lower().replace(' ','_')}.png"
        img.convert("RGBA").save(out)
        return out.relative_to(APP_DIR).as_posix()
    except Exception:
        return ""

def ingest_dialog_portrait(src_path: str) -> str:
    """Copy portrait into icons/dialog_portraits/ and return a project-relative path."""
    try:
        src = Path(src_path)
        PORTRAITS_DIR.mkdir(parents=True, exist_ok=True)
        safe_name = src.name.replace(" ", "_")
        dest = PORTRAITS_DIR / safe_name
        i = 1
        while dest.exists():
            stem, suf = os.path.splitext(safe_name)
            dest = PORTRAITS_DIR / f"{stem}_{i}{suf}"
            i += 1
        shutil.copy2(src, dest)
        return dest.relative_to(APP_DIR).as_posix()
    except Exception:
        return src_path.replace("\\", "/")

def count_dialog_blocks_from_text(text: str) -> int:
    lines = [ln.rstrip() for ln in text.replace("\r\n","\n").split("\n")]
    blocks, buf = 0, []
    for ln in lines:
        if ln.strip() == "":
            if buf:
                blocks += 1
                buf = []
        else:
            buf.append(ln)
    if buf:
        blocks += 1
    return blocks

# =========================
# Dialogs
# =========================
class StatusPopup(QDialog):
    def __init__(self, parent, current: List[str]):
        super().__init__(parent)
        self.setWindowTitle("Statuses")
        self.setModal(True)
        self.vars: Dict[str, QCheckBox] = {}
        grid = QGridLayout(self)
        r=c=0
        current_norm = set(s.lower().replace(" ","_") for s in (current or []))
        for key in STATUS_KEYS:
            cb = QCheckBox(key.replace("_"," ").capitalize())
            cb.setChecked(key in current_norm)
            grid.addWidget(cb, r, c); self.vars[key]=cb
            c+=1
            if c>=3: c=0; r+=1
        btns = QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        grid.addWidget(btns, r+1, 0, 1, 3)
    def selected(self)->List[str]:
        return [k for k,cb in self.vars.items() if cb.isChecked()]

# (Popup kept simple; inline controls handle offsets + scale)

# =========================
# Main Window (GM)
# =========================
class GMWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GM Control Panel")
        self.resize(1200, 780)

        self.store = PartyStore()

        # Menus: Light/Dark
        self._build_menus()

        # Panels & layout
        self._build_topbar()
        self._build_party_list()
        self._build_editor()
        self._build_active_and_dialog()

        right_split = QSplitter(Qt.Vertical)
        right_split.addWidget(self.editor_panel)
        right_split.addWidget(self.bottom_panel)
        right_split.setSizes([420, 340])

        main_split = QSplitter(Qt.Horizontal)
        main_split.addWidget(self.party_panel)
        main_split.addWidget(right_split)
        main_split.setSizes([320, 840])

        central = QWidget()
        v = QVBoxLayout(central); v.setContentsMargins(6,6,6,6)
        tb_wrap = QWidget(); tb_wrap.setLayout(self.topbar)
        v.addWidget(tb_wrap); v.addWidget(main_split)
        self.setCentralWidget(central)

        # overlay process handle
        self._overlay_proc = None

        # Hotkeys when GM has focus
        self._make_shortcuts()

        # Init UI
        self.refresh_party()
        self.refresh_table()
        self.load_dialog_into_editor()

    # ---- Menus ----
    def _build_menus(self):
        bar = self.menuBar()
        view = bar.addMenu("View")
        act_light = QAction("Light UI", self, checkable=True)
        act_dark  = QAction("Dark UI", self, checkable=True)

        def set_ui(mode):
            act_light.setChecked(mode=="light")
            act_dark.setChecked(mode=="dark")
            apply_gm_ui_qss(mode)

        act_light.triggered.connect(lambda _: set_ui("light"))
        act_dark.triggered.connect(lambda _: set_ui("dark"))
        view.addAction(act_light); view.addAction(act_dark)
        set_ui("dark")  # default dark

    # ----- UI: topbar -----
    def _build_topbar(self):
        self.topbar = QHBoxLayout(); self.topbar.setContentsMargins(8,8,8,8)

        btn_launch = QPushButton("Launch Overlay"); btn_launch.clicked.connect(lambda: self.launch_overlay(normal=True))
        btn_stop   = QPushButton("Stop Overlay");   btn_stop.clicked.connect(self.stop_overlay)

        self.btn_combat = QPushButton(self._combat_text()); self.btn_combat.clicked.connect(self.toggle_combat)

        # Turn + Dialog controls
        btn_prev = QPushButton("⟵ Prev Turn"); btn_prev.clicked.connect(self.prev_turn)
        btn_next = QPushButton("Next Turn ⟶"); btn_next.clicked.connect(self.next_turn)
        btn_dprev = QPushButton("Prev Line (,)"); btn_dprev.clicked.connect(self.prev_dialog)
        btn_dnext = QPushButton("Next Line (.)"); btn_dnext.clicked.connect(self.next_dialog)

        # Overlay theme
        lbl_theme = QLabel("Overlay Theme:")
        cmb_theme = QComboBox()
        names = ["(default)"] + [d.name for d in THEMES_DIR.iterdir() if (d/"theme.json").exists()] if THEMES_DIR.exists() else ["(default)"]
        cmb_theme.addItems(names)
        current_label = self.store.config.get("theme","")
        cmb_theme.setCurrentText(current_label if current_label else "(default)")
        cmb_theme.currentTextChanged.connect(
            lambda text: self.switch_overlay_theme(None if text=="(default)" else text)
        )

        btn_legend = QPushButton("Status Legend"); btn_legend.clicked.connect(self.show_legend)
        btn_reload = QPushButton("Reload (R)");    btn_reload.clicked.connect(self.reload_files)
        btn_save   = QPushButton("Save All");       btn_save.clicked.connect(self.save_all)

        for w in (btn_launch, btn_stop, QLabel(" | "), self.btn_combat, btn_prev, btn_next,
                  QLabel(" | "), btn_dprev, btn_dnext, QLabel(" | "),
                  lbl_theme, cmb_theme, QLabel(" | "), btn_legend, btn_reload, btn_save):
            self.topbar.addWidget(w)
        self.topbar.addStretch()

    def switch_overlay_theme(self, theme_name: Optional[str]):
        stored = "" if (theme_name is None) else theme_name
        self.store.config["theme"] = stored
        self.store.save_config()

    # ----- UI: roster -----
    def _build_party_list(self):
        self.party_panel = QGroupBox("Roster")
        lay = QVBoxLayout(self.party_panel)
        self.listbox = QListWidget()
        self.listbox.setSelectionMode(QListWidget.ExtendedSelection)
        self.listbox.currentRowChanged.connect(self.on_select)
        lay.addWidget(self.listbox)

        # Encounter control
        row = QHBoxLayout()
        b_add_enc = QPushButton("➕ Add Selected to Encounter"); b_add_enc.clicked.connect(self.mark_selected_active)
        b_rem_enc = QPushButton("➖ Remove Selected");            b_rem_enc.clicked.connect(self.unmark_selected_active)
        row.addWidget(b_add_enc); row.addWidget(b_rem_enc); lay.addLayout(row)

        # Remove & Clear Form
        btns = QHBoxLayout()
        b_add = QPushButton("Add / Clear Form"); b_add.clicked.connect(self.add_member_clear)
        b_del = QPushButton("Remove Selected");  b_del.clicked.connect(self.remove_member)
        btns.addWidget(b_add); btns.addWidget(b_del)
        lay.addLayout(btns)

    # ----- UI: editor -----
    def _build_editor(self):
        self.editor_panel = QGroupBox("Selected Character")
        g = QGridLayout(self.editor_panel)

        self.ent_name = QLineEdit();       self._grid(g, "Name", self.ent_name, 0)
        self.spn_max  = QSpinBox();        self.spn_max.setRange(0, 9999); self._grid(g, "Max HP", self.spn_max, 1)
        self.spn_cur  = QSpinBox();        self.spn_cur.setRange(0, 9999); self._grid(g, "Current HP", self.spn_cur, 2)
        self.chk_enemy= QCheckBox("Is Enemy"); g.addWidget(self.chk_enemy, 3,1)

        self.spn_mod  = QSpinBox();        self.spn_mod.setRange(-20, 20); self._grid(g, "Init Mod", self.spn_mod, 4)

        self.ent_icon = QLineEdit();       self._grid(g, "Icon (PNG/JPG)", self.ent_icon, 5)
        btn_browse = QPushButton("Browse…"); btn_browse.clicked.connect(self.pick_icon); g.addWidget(btn_browse, 5, 2)

        # initiative (this fight)
        self.spn_init = QSpinBox(); self.spn_init.setRange(-999, 999)
        self._grid(g, "Initiative (this fight)", self.spn_init, 6)

        self.btn_status = QPushButton("Statuses…"); self.btn_status.clicked.connect(self.edit_statuses)
        g.addWidget(self.btn_status, 7, 1)

        btn_save = QPushButton("Save Changes"); btn_save.clicked.connect(self.apply_changes)
        g.addWidget(btn_save, 8, 1)

        # HP quick adjust
        g.addWidget(QLabel("HP Quick Adjust"), 9, 0)
        quick = QHBoxLayout()
        for txt,val in [("-5",-5),("-1",-1),("+1",+1),("+5",+5)]:
            b=QPushButton(txt); b.clicked.connect(lambda _,v=val:self.bump_hp(v))
            quick.addWidget(b)
        wrap = QWidget(); wrap.setLayout(quick); g.addWidget(wrap, 9, 1)

    # ----- UI: active table + dialog editor -----
    def _build_active_and_dialog(self):
        self.bottom_panel = QGroupBox("Active Combatants + Dialog Editor")
        v = QVBoxLayout(self.bottom_panel)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Turn","Name","Init Roll","Mod","FX","Type"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        v.addWidget(self.table)

        dlg_box = QGroupBox("Dialog Editor (dialog.txt)")
        dv = QVBoxLayout(dlg_box)
        self.dlg_edit = QPlainTextEdit()
        self.dlg_edit.setPlaceholderText("Each paragraph (blank line separated) becomes one dialog block.")

        # top row: open/reload/save + block index
        row = QHBoxLayout()
        self.block_idx_spin = QSpinBox(); self.block_idx_spin.setRange(0, 0)
        self.block_idx_spin.valueChanged.connect(self._load_block_meta_into_fields)

        btn_load = QPushButton("Reload from File"); btn_load.clicked.connect(self.load_dialog_into_editor)
        btn_save = QPushButton("Save to File");     btn_save.clicked.connect(self.save_dialog_from_editor)
        row.addWidget(QLabel("Block #")); row.addWidget(self.block_idx_spin)
        row.addStretch(); row.addWidget(btn_load); row.addWidget(btn_save)

        # second row: portrait + offsets + scale
        prow = QHBoxLayout()
        self.portrait_edit = QLineEdit(); self.portrait_edit.setPlaceholderText("Portrait for current block (PNG/JPG)")
        btn_por_browse = QPushButton("Browse…"); btn_por_browse.clicked.connect(self.pick_dialog_portrait)
        self.spn_offx = QSpinBox(); self.spn_offx.setRange(-1000, 2000); self.spn_offx.setValue(20)
        self.spn_offy = QSpinBox(); self.spn_offy.setRange(-1000, 2000); self.spn_offy.setValue(-120)
        self.dbl_scale= QDoubleSpinBox(); self.dbl_scale.setRange(0.1, 3.0); self.dbl_scale.setSingleStep(0.1); self.dbl_scale.setValue(1.0)
        btn_por_save = QPushButton("Save Portrait & Offsets"); btn_por_save.clicked.connect(self.save_current_block_portrait)
        btn_por_clear= QPushButton("Clear Portrait");          btn_por_clear.clicked.connect(self.clear_current_block_portrait)

        prow.addWidget(self.portrait_edit); prow.addWidget(btn_por_browse)
        prow.addWidget(QLabel("Offset X")); prow.addWidget(self.spn_offx)
        prow.addWidget(QLabel("Offset Y")); prow.addWidget(self.spn_offy)
        prow.addWidget(QLabel("Scale"));    prow.addWidget(self.dbl_scale)
        prow.addWidget(btn_por_save); prow.addWidget(btn_por_clear)

        dv.addWidget(self.dlg_edit); dv.addLayout(row); dv.addLayout(prow)
        v.addWidget(dlg_box)

    # ----- helpers -----
    def _grid(self, grid: QGridLayout, label: str, w: QWidget, row: int):
        grid.addWidget(QLabel(label), row, 0, alignment=Qt.AlignRight)
        grid.addWidget(w, row, 1)

    def _make_shortcuts(self):
        for key, slot in [("Right", self.next_turn), ("Left", self.prev_turn),
                          (",", self.prev_dialog), (".", self.next_dialog),
                          ("C", self.toggle_combat), ("R", self.reload_files)]:
            act = QAction(self); act.setShortcut(key); act.triggered.connect(slot); self.addAction(act)

    # ----- data views -----
    def party_view_sorted(self)->List[PartyMember]:
        return sorted(self.store.party, key=lambda m:(m.turnOrder==0, m.isEnemy, m.turnOrder, m.name.lower()))

    def active_members(self)->List[PartyMember]:
        return [m for m in self.party_view_sorted() if m.active]

    def refresh_party(self):
        self.listbox.clear()
        for m in self.party_view_sorted():
            tag = "[E]" if m.isEnemy else "[P]"
            act = " (Active)" if m.active else ""
            self.listbox.addItem(QListWidgetItem(f"{tag} {m.name}{act}  (Init:{m.turnOrder or 0}  Mod:{m.initMod:+})"))

    def refresh_table(self):
        self.table.setRowCount(0)
        for m in self.active_members():
            row = self.table.rowCount(); self.table.insertRow(row)
            fx = " ".join(STATUS_EMOJI.get(s.lower(), s[:1].upper()) for s in (m.statusEffects or []))
            vals = [m.turnOrder or 0, m.name, m.initiative if m.initiative is not None else "",
                    f"{m.initMod:+}", fx, "Enemy" if m.isEnemy else "Player"]
            for c,val in enumerate(vals):
                self.table.setItem(row, c, QTableWidgetItem(str(val)))

    # ----- dialog editor -----
    def _update_block_index_bounds_from_text(self, text: str):
        blocks = max(0, count_dialog_blocks_from_text(text) - 1)
        self.block_idx_spin.setRange(0, blocks)
        self._load_block_meta_into_fields()  # refresh fields for current index

    def _load_block_meta_into_fields(self):
        meta = self.store.dialog_meta.get(str(self.block_idx_spin.value()), {})
        self.portrait_edit.setText(meta.get("portrait", ""))
        self.spn_offx.setValue(int(meta.get("portrait_offset_x", 20)))
        self.spn_offy.setValue(int(meta.get("portrait_offset_y", -120)))
        self.dbl_scale.setValue(float(meta.get("portrait_scale", 1.0)))

    def load_dialog_into_editor(self):
        try:
            text = DIALOG_FILE.read_text(encoding="utf-8")
        except Exception:
            text = ""
        self.dlg_edit.setPlainText(text)
        self._update_block_index_bounds_from_text(text)

    def save_dialog_from_editor(self):
        text = self.dlg_edit.toPlainText().replace("\r\n","\n")
        DIALOG_FILE.write_text(text, encoding="utf-8")
        self.store.save_dialog_meta()
        self._update_block_index_bounds_from_text(text)
        QMessageBox.information(self, "Dialog", "dialog.txt and dialog_meta.json saved.")

    def pick_dialog_portrait(self):
        p,_ = QFileDialog.getOpenFileName(self, "Choose Portrait", str(APP_DIR), "Images (*.png *.jpg *.jpeg *.webp)")
        if p: self.portrait_edit.setText(p)

    def save_current_block_portrait(self):
        path = self.portrait_edit.text().strip()
        idx  = str(self.block_idx_spin.value())
        if path:
            rel = ingest_dialog_portrait(path)
        else:
            rel = self.store.dialog_meta.get(idx, {}).get("portrait", "")
        self.store.dialog_meta[idx] = {
            "portrait": rel,
            "portrait_offset_x": int(self.spn_offx.value()),
            "portrait_offset_y": int(self.spn_offy.value()),
            "portrait_scale": float(self.dbl_scale.value()),
        }
        self.store.save_dialog_meta()
        QMessageBox.information(self, "Portrait", f"Saved portrait + offsets for block {idx}.")

    def clear_current_block_portrait(self):
        idx = str(self.block_idx_spin.value())
        if idx in self.store.dialog_meta:
            del self.store.dialog_meta[idx]
            self.store.save_dialog_meta()
            self._load_block_meta_into_fields()
            QMessageBox.information(self, "Portrait", f"Cleared portrait for block {idx}.")

    # ----- selection mapping -----
    def _current_index(self)->Optional[int]:
        vis_idx = self.listbox.currentRow()
        if vis_idx < 0: return None
        target_name = self.party_view_sorted()[vis_idx].name
        for i,m in enumerate(self.store.party):
            if m.name == target_name: return i
        return None

    # ----- roster actions -----
    def on_select(self, _row):
        idx = self._current_index()
        if idx is None: return
        m = self.store.party[idx]
        self.ent_name.setText(m.name)
        self.spn_max.setValue(m.maxHP)
        self.spn_cur.setValue(m.currentHP)
        self.chk_enemy.setChecked(m.isEnemy)
        self.spn_mod.setValue(m.initMod)
        self.ent_icon.setText(m.icon)
        self.spn_init.setValue(m.initiative if m.initiative is not None else 0)

    def add_member_clear(self):
        self.listbox.clearSelection()
        self.ent_name.clear(); self.ent_icon.clear()
        self.spn_max.setValue(0); self.spn_cur.setValue(0); self.spn_mod.setValue(0); self.spn_init.setValue(0)
        self.chk_enemy.setChecked(False)

    def remove_member(self):
        items = self.listbox.selectedItems()
        if not items:
            QMessageBox.information(self, "Remove", "Select one or more characters to remove.")
            return
        names = [it.text().split(" ",1)[1].split("  (",1)[0] for it in items]
        if QMessageBox.question(self, "Remove", f"Remove {len(names)} selected?") != QMessageBox.Yes:
            return
        self.store.party = [m for m in self.store.party if m.name not in names]
        self.store.save_party()
        self._clamp_turn_index()
        self.refresh_party(); self.refresh_table()

    def pick_icon(self):
        p,_ = QFileDialog.getOpenFileName(self, "Select Icon", str(APP_DIR), "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if p: self.ent_icon.setText(p)

    def apply_changes(self):
        name = self.ent_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Error", "Name is required"); return
        maxhp = self.spn_max.value()
        curhp = max(0, min(self.spn_cur.value(), maxhp))
        is_enemy = self.chk_enemy.isChecked()
        initmod = self.spn_mod.value()
        initiative_val = self.spn_init.value()
        idx = self._current_index()

        if idx is None:
            m = PartyMember(name=name, maxHP=maxhp, currentHP=curhp, isEnemy=is_enemy)
            self.store.party.append(m)
            idx = len(self.store.party)-1
        m = self.store.party[idx]
        m.name=name; m.maxHP=maxhp; m.currentHP=curhp; m.isEnemy=is_enemy; m.initMod=initmod
        m.initiative = initiative_val

        if self.store.config.get("combat_mode", False) and (m.initiative is None or m.initiative == 0):
            m.initiative = random.randint(1,20) + (m.initMod or 0)

        icon_src = self.ent_icon.text().strip()
        if icon_src:
            rel = process_icon_to_gray(Path(icon_src), name)
            if rel: m.icon=rel
        if m.statusEffects is None: m.statusEffects=[]

        self.store.save_party()

        if self.store.config.get("combat_mode", False):
            active_name = ""
            actives = self.active_members()
            if actives:
                cur_idx = self.store.config.get("turnIndex",0)
                if 0 <= cur_idx < len(actives):
                    active_name = actives[cur_idx].name
            self.store.sort_by_initiative()
            if active_name:
                actives = self.active_members()
                for i, mm in enumerate(actives):
                    if mm.name == active_name:
                        self.store.config["turnIndex"] = i
                        self.store.save_config()
                        break

        self.refresh_party(); self.refresh_table()

    def bump_hp(self, delta: int):
        idx = self._current_index()
        if idx is None: return
        m = self.store.party[idx]
        if m.isEnemy: return
        m.currentHP = max(0, min(m.currentHP + delta, m.maxHP))
        self.store.save_party()
        self.refresh_table()

    # ----- statuses -----
    def edit_statuses(self):
        idx = self._current_index()
        if idx is None:
            name = self.ent_name.text().strip()
            if not name:
                QMessageBox.information(self, "Statuses", "Enter a Name, then click Save Changes first.")
                return
            self.apply_changes()
            idx = self._current_index()
            if idx is None:
                QMessageBox.information(self, "Statuses", "Select a character first.")
                return

        m = self.store.party[idx]
        dlg = StatusPopup(self, m.statusEffects or [])
        if dlg.exec() == QDialog.Accepted:
            m.statusEffects = dlg.selected()
            self.store.save_party()
            self.refresh_table()

    def show_legend(self):
        QMessageBox.information(self, "Status Legend",
            "Badges use icons from icons/status/ (e.g., poisoned.png).\n"
            "If missing, we show a letter fallback.\n\n"
            "Keys supported out of the box:\n" + ", ".join(STATUS_KEYS))

    # ----- encounter controls -----
    def mark_selected_active(self):
        idx = self._current_index()
        if idx is None:
            QMessageBox.information(self, "Encounter", "Select a character in the roster first.")
            return
        self.store.party[idx].active = True
        self.store.save_party()
        self._clamp_turn_index()
        self.refresh_party(); self.refresh_table()

    def unmark_selected_active(self):
        idx = self._current_index()
        if idx is None:
            QMessageBox.information(self, "Encounter", "Select a character in the roster first.")
            return
        self.store.party[idx].active = False
        self.store.save_party()
        self._clamp_turn_index()
        self.refresh_party(); self.refresh_table()

    def _clamp_turn_index(self):
        actives = self.active_members()
        if not actives:
            self.store.config["turnIndex"] = 0
        else:
            self.store.config["turnIndex"] = min(self.store.config.get("turnIndex",0), len(actives)-1)
        self.store.save_config()

    # ----- combat control -----
    def _combat_text(self)->str:
        return "Combat: ON" if self.store.config.get("combat_mode", False) else "Combat: OFF"

    def ensure_initiatives(self):
        for m in self.store.party:
            if not m.active: continue
            if m.initiative is None or m.initiative == 0:
                m.initiative = random.randint(1,20) + (m.initMod or 0)
        self.store.save_party()

    def toggle_combat(self):
        self.store.config["combat_mode"] = not self.store.config.get("combat_mode", False)
        if self.store.config["combat_mode"]:
            self.ensure_initiatives()
            self.store.sort_by_initiative()
            self.store.config["turnIndex"] = 0
        self.store.save_config()
        self.btn_combat.setText(self._combat_text())
        self.refresh_party(); self.refresh_table()

    def next_turn(self):
        actives = self.active_members()
        if not actives: return
        self.store.config["turnIndex"] = (self.store.config.get("turnIndex",0)+1) % len(actives)
        self.store.save_config()

    def prev_turn(self):
        actives = self.active_members()
        if not actives: return
        self.store.config["turnIndex"] = (self.store.config.get("turnIndex",0)-1) % len(actives)
        self.store.save_config()

    def next_dialog(self):
        self.store.config["dialogIndex"] = self.store.config.get("dialogIndex",0) + 1
        self.store.save_config()

    def prev_dialog(self):
        self.store.config["dialogIndex"] = max(0, self.store.config.get("dialogIndex",0)-1)
        self.store.save_config()

    # ----- overlay -----
    def launch_overlay(self, normal=True):
        try:
            if not OVERLAY_PY.exists():
                raise FileNotFoundError(f"{OVERLAY_PY} not found")
            py = Path(sys.executable)
            if os.name == "nt":
                pyw = py.with_name("pythonw.exe")
                exe = str(pyw if pyw.exists() else py)
            else:
                exe = str(py)
            self._overlay_proc = subprocess.Popen([exe, str(OVERLAY_PY)], cwd=str(APP_DIR))
            try:
                self._overlay_proc.wait(timeout=1)
            except Exception:
                pass
            if self._overlay_proc.poll() not in (None, 0):
                raise RuntimeError("Overlay exited on startup.")
        except Exception as e:
            self._overlay_proc = None
            if QMessageBox.question(self, "Overlay Launch Failed",
                                    f"{e}\n\nLaunch in Debug Mode to see errors?",
                                    QMessageBox.Yes|QMessageBox.No) == QMessageBox.Yes:
                self._overlay_proc = subprocess.Popen([sys.executable, str(OVERLAY_PY), "--debug"], cwd=str(APP_DIR))

    def stop_overlay(self):
        if self._overlay_proc and self._overlay_proc.poll() is None:
            try:
                self._overlay_proc.terminate()
            except Exception:
                pass
            self._overlay_proc = None
        else:
            QMessageBox.information(self, "Overlay", "Overlay is not running.")

    # ----- file I/O -----
    def reload_files(self):
        self.store.party = self.store.load_party()
        self.store.config = self.store.load_config()
        self.store.dialog_meta = self.store.load_dialog_meta()
        self.btn_combat.setText(self._combat_text())
        self.refresh_party(); self.refresh_table()
        self.load_dialog_into_editor()

    def save_all(self):
        self.store.save_party(); self.store.save_config(); self.store.save_dialog_meta()
        QMessageBox.information(self, "Saved", "party.json, config.json, dialog_meta.json saved.")

def main():
    app = QApplication(sys.argv)
    win = GMWindow()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
