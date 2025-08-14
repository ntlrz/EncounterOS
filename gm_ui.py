from __future__ import annotations

import json, random, subprocess, sys, os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional

from PIL import Image
from PySide6.QtCore import Qt, QSize, QRect
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton, QListWidget, QListWidgetItem,
    QLineEdit, QSpinBox, QCheckBox, QFileDialog, QMessageBox, QGridLayout, QHBoxLayout,
    QVBoxLayout, QGroupBox, QTableWidget, QTableWidgetItem, QHeaderView, QDialog, QDialogButtonBox
)

# =========================
# Paths & constants
# =========================
APP_DIR       = Path(__file__).resolve().parent
PARTY_FILE    = APP_DIR / "party.json"
CONFIG_FILE   = APP_DIR / "config.json"
ICONS_DIR     = APP_DIR / "icons"
STATUS_DIR    = ICONS_DIR / "status"
THEMES_DIR    = APP_DIR / "themes"
OVERLAY_PY    = APP_DIR / "tracker_overlay.py"

ICON_SIZE     = (64, 64)
STATUS_KEYS   = [
    # starter set (add more freely)
    "poisoned","stunned","prone","concentrating","blessed","hexed","frightened","invisible",
    "grappled","restrained","paralyzed","petrified","deafened","blinded","baned","blessed",
]
STATUS_EMOJI  = {"poisoned":"☠️","stunned":"💫","prone":"🛏️","concentrating":"🎯","blessed":"✨",
                 "hex":"🪄","frightened":"😱","invisible":"👻","grappled":"🤼","restrained":"⛓️",
                 "paralyzed":"🧊","petrified":"🗿","deafened":"🔕","blinded":"🙈","baned":"⛔"}

# =========================
# Theme support (grid + QSS)
# =========================
class ThemeManager:
    """
    Loads a theme by name from themes/<name>/theme.json and applies its QSS to the app.
    Exposes a simple grid layout for RegionHost via region_rect().
    """
    def __init__(self, app: QApplication):
        self.app = app
        # Built-in defaults (safe if no theme folder exists)
        self.vars = {"scale": 1.0}
        self.grid = {
            "grid":  {"cols": 24, "rows": 24, "margin": 8, "gutter": 8},
            "regions": {
                "topbar":       {"gridRect": [0, 0, 24, 2]},
                "party_list":   {"gridRect": [0, 2, 8, 16]},
                "editor":       {"gridRect": [8, 2, 16, 16]},
                "combat_table": {"gridRect": [0, 18, 24, 6]},
            }
        }

    @staticmethod
    def available_theme_names() -> List[str]:
        if not THEMES_DIR.exists():
            return []
        names = []
        for sub in THEMES_DIR.iterdir():
            if (sub / "theme.json").exists():
                names.append(sub.name)
        return sorted(names)

    def load_theme(self, theme_name: str | None):
        """Load theme.json + style.qss (if any). If None or missing, reset to defaults."""
        # Reset to defaults first
        self.vars = {"scale": 1.0}
        self.grid = {
            "grid":  {"cols": 24, "rows": 24, "margin": 8, "gutter": 8},
            "regions": {
                "topbar":       {"gridRect": [0, 0, 24, 2]},
                "party_list":   {"gridRect": [0, 2, 8, 16]},
                "editor":       {"gridRect": [8, 2, 16, 16]},
                "combat_table": {"gridRect": [0, 18, 24, 6]},
            }
        }
        self.app.setStyleSheet("")  # clear previous

        if not theme_name:
            return  # defaults

        tdir = THEMES_DIR / theme_name
        tjson = tdir / "theme.json"
        if not tjson.exists():
            return  # fallback to defaults silently

        try:
            data = json.loads(tjson.read_text(encoding="utf-8"))
            # merge vars
            self.vars.update(data.get("vars", {}))
            # grid
            layout = data.get("layout", {})
            grid = layout.get("grid", {})
            self.grid["grid"].update(grid)
            regions = layout.get("regions", {})
            if regions:
                self.grid["regions"].update(regions)
            # QSS
            qss_file = data.get("qss")
            if qss_file:
                qss_path = tdir / qss_file
                if qss_path.exists():
                    qss = qss_path.read_text(encoding="utf-8")
                    for k, v in self.vars.items():
                        qss = qss.replace("${" + k + "}", str(v))
                    self.app.setStyleSheet(qss)
        except Exception:
            pass
          
    def region_rect(self, win_size, region_id: str):
        """Convert a region's gridRect into pixel QRect for the current window size."""
        g = self.grid["grid"]
        regions = self.grid["regions"]
        cols, rows = g["cols"], g["rows"]
        margin, gutter = g["margin"], g["gutter"]
        # fallback to full grid if region not found
        r = regions.get(region_id, {"gridRect": [0, 0, cols, rows]})["gridRect"]
        x, y, w, h = r

        cell_w = (win_size.width()  - 2*margin - gutter*(cols - 1)) / cols
        cell_h = (win_size.height() - 2*margin - gutter*(rows - 1)) / rows

        px = round(margin + x * (cell_w + gutter))
        py = round(margin + y * (cell_h + gutter))
        pw = round(w * cell_w + (w - 1) * gutter)
        ph = round(h * cell_h + (h - 1) * gutter)
        from PySide6.QtCore import QRect
        return QRect(px, py, pw, ph)


class RegionHost(QWidget):
    """Holds named child panels positioned by ThemeManager grid."""
    def __init__(self, theme: ThemeManager, parent=None):
        super().__init__(parent)
        self.theme = theme
        self._mounted: Dict[str, QWidget] = {}

    def mount(self, region_id: str, widget: QWidget):
        self._mounted[region_id] = widget
        widget.setParent(self)
        widget.show()
        self.relayout()

    def relayout(self):
        for region_id, w in self._mounted.items():
            w.setGeometry(self.theme.region_rect(self.size(), region_id))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.relayout()

def region_rect(tm: ThemeManager, win_size, region_id: str) -> QRect:
    g = tm.grid["grid"]; regions = tm.grid["regions"]
    cols, rows = g["cols"], g["rows"]
    margin, gutter = g["margin"], g["gutter"]
    r = regions.get(region_id, {"gridRect": [0, 0, cols, rows]})["gridRect"]
    x, y, w, h = r
    cell_w = (win_size.width()  - 2*margin - gutter*(cols-1)) / cols
    cell_h = (win_size.height() - 2*margin - gutter*(rows-1)) / rows
    px = round(margin + x * (cell_w + gutter))
    py = round(margin + y * (cell_h + gutter))
    pw = round(w * cell_w + (w-1) * gutter)
    ph = round(h * cell_h + (h-1) * gutter)
    return QRect(px, py, pw, ph)

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
    icon: str = ""                 # relative path (from app dir)
    statusEffects: List[str] = None
    initMod: int = 0
    initiative: Optional[int] = None

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
        )
    def to_dict(self)->Dict: return asdict(self)

class PartyStore:
    def __init__(self):
        ICONS_DIR.mkdir(parents=True, exist_ok=True)
        STATUS_DIR.mkdir(parents=True, exist_ok=True)
        if not PARTY_FILE.exists(): PARTY_FILE.write_text(json.dumps({"party":[]}, indent=2), encoding="utf-8")
        if not CONFIG_FILE.exists(): CONFIG_FILE.write_text(json.dumps({"combat_mode":False,"turnIndex":0,"dialogIndex":0,"theme":"gm-modern"}, indent=2), encoding="utf-8")
        self.party: List[PartyMember] = self.load_party()
        self.config: Dict = self.load_config()

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

    def sort_by_initiative(self):
        self.party.sort(key=lambda m:(m.initiative or 0, m.name.lower()), reverse=True)
        for i,m in enumerate(self.party, start=1):
            m.turnOrder=i
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
        for key in STATUS_KEYS:
            cb = QCheckBox(key.replace("_"," ").capitalize())
            cb.setChecked(key in (s.lower().replace(" ","_") for s in current))
            grid.addWidget(cb, r, c); self.vars[key]=cb
            c+=1
            if c>=3: c=0; r+=1
        btns = QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        grid.addWidget(btns, r+1, 0, 1, 3)
    def selected(self)->List[str]:
        return [k for k,cb in self.vars.items() if cb.isChecked()]

class StatusLegend(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Status Legend")
        layout=QVBoxLayout(self)
        table=QTableWidget(0,2)
        table.setHorizontalHeaderLabels(["Status key","Emoji/Alt"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(table)
        for key in STATUS_KEYS:
            row=table.rowCount(); table.insertRow(row)
            table.setItem(row,0,QTableWidgetItem(key))
            table.setItem(row,1,QTableWidgetItem(STATUS_EMOJI.get(key,key[:1].upper())))
        btn = QPushButton("Open Status Folder"); btn.clicked.connect(lambda: subprocess.Popen(["explorer", str(STATUS_DIR)]))
        layout.addWidget(btn)

# =========================
# Main Window (GM)
# =========================
class GMWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GM Control Panel")
        self.resize(1100, 720)

        self.store = PartyStore()

        # theme (load from config)
        self.theme = ThemeManager(QApplication.instance())
        self.current_theme = self.store.config.get("theme", "gm-modern")
        self.theme.load_theme(self.current_theme)

        # Region host
        self.host = RegionHost(self.theme)
        self.setCentralWidget(self.host)

        # Build panels
        self._build_topbar()
        self._build_party_list()
        self._build_editor()
        self._build_combat_table()

        # Mount panels
        self.host.mount("topbar",       self.topbar)
        self.host.mount("party_list",   self.party_panel)
        self.host.mount("editor",       self.editor_panel)
        self.host.mount("combat_table", self.table_panel)

        # Menu: Themes
        self._build_theme_menu()

        # Hotkeys when GM has focus
        self._make_shortcuts()

        self.refresh_party()
        self.refresh_table()

    # ---- Menus
    def _build_theme_menu(self):
        bar = self.menuBar()
        menu = bar.addMenu("Themes")
        self.theme_actions: List[QAction] = []
        names = ThemeManager.available_theme_names() or ["(default)"]
        for name in names:
            act = QAction(name, self, checkable=True, checked=(name == self.current_theme))
            act.triggered.connect(lambda checked, n=name: self.switch_theme(None if n=="(default)" else n))
            menu.addAction(act)
            self.theme_actions.append(act)

    def switch_theme(self, theme_name: Optional[str]):
        for a in self.theme_actions:
            a.setChecked(a.text() == (theme_name or "(default)"))
        self.current_theme = theme_name
        self.store.config["theme"] = theme_name or None
        self.store.save_config()
        self.theme.load_theme(self.current_theme)
        self.host.relayout()

    # ----- UI: topbar
    def _build_topbar(self):
        self.topbar = QWidget(objectName="topbar")
        row = QHBoxLayout(self.topbar); row.setContentsMargins(8,8,8,8)

        btn_launch = QPushButton("Launch Overlay")
        btn_launch.clicked.connect(lambda: self.launch_overlay(normal=True))
        btn_stop   = QPushButton("Stop Overlay")
        btn_stop.clicked.connect(self.stop_overlay)

        self.btn_combat = QPushButton(self._combat_text()); self.btn_combat.clicked.connect(self.toggle_combat)

        # Turn controls
        lbl_turn = QLabel("Turn:")
        btn_prev = QPushButton("⟵ Prev"); btn_prev.clicked.connect(self.prev_turn)
        btn_next = QPushButton("Next ⟶"); btn_next.clicked.connect(self.next_turn)

        # Dialog controls
        lbl_dlg = QLabel("Dialog:")
        btn_dprev = QPushButton("Prev (,)")
        btn_dprev.clicked.connect(self.prev_dialog)
        btn_dnext = QPushButton("Next (.)")
        btn_dnext.clicked.connect(self.next_dialog)

        btn_legend = QPushButton("Status Legend"); btn_legend.clicked.connect(self.show_legend)
        btn_reload = QPushButton("Reload (R)");   btn_reload.clicked.connect(self.reload_files)
        btn_save   = QPushButton("Save All");      btn_save.clicked.connect(self.save_all)

        for w in (btn_launch, btn_stop, self.btn_combat, lbl_turn, btn_prev, btn_next,
                  lbl_dlg, btn_dprev, btn_dnext, btn_legend, btn_reload, btn_save):
            row.addWidget(w)
        row.addStretch()

        # Hidden until needed:
        self._debug_btn = None  # created on demand

    # ----- UI: roster
    def _build_party_list(self):
        self.party_panel = QGroupBox("Roster", objectName="party_list")
        lay = QVBoxLayout(self.party_panel)
        self.listbox = QListWidget()
        self.listbox.currentRowChanged.connect(self.on_select)
        lay.addWidget(self.listbox)

        btns = QHBoxLayout()
        b_add = QPushButton("Add / Clear Form"); b_add.clicked.connect(self.add_member_clear)
        b_del = QPushButton("Remove Selected");  b_del.clicked.connect(self.remove_member)
        btns.addWidget(b_add); btns.addWidget(b_del)
        lay.addLayout(btns)

    # ----- UI: editor
    def _build_editor(self):
        self.editor_panel = QGroupBox("Selected Character", objectName="editor")
        g = QGridLayout(self.editor_panel)

        self.ent_name = QLineEdit();       self._grid(g, "Name", self.ent_name, 0)
        self.spn_max  = QSpinBox();        self.spn_max.setRange(0, 9999); self._grid(g, "Max HP", self.spn_max, 1)
        self.spn_cur  = QSpinBox();        self.spn_cur.setRange(0, 9999); self._grid(g, "Current HP", self.spn_cur, 2)
        self.chk_enemy= QCheckBox("Is Enemy"); g.addWidget(self.chk_enemy, 3,1)

        self.spn_mod  = QSpinBox();        self.spn_mod.setRange(-20, 20); self._grid(g, "Init Mod", self.spn_mod, 4)

        self.ent_icon = QLineEdit();       self._grid(g, "Icon (PNG/JPG)", self.ent_icon, 5)
        btn_browse = QPushButton("Browse…"); btn_browse.clicked.connect(self.pick_icon); g.addWidget(btn_browse, 5, 2)

        self.btn_status = QPushButton("Statuses…"); self.btn_status.clicked.connect(self.edit_statuses)
        g.addWidget(self.btn_status, 6, 1)

        btn_save = QPushButton("Save Changes"); btn_save.clicked.connect(self.apply_changes)
        g.addWidget(btn_save, 7, 1)

        # HP quick adjust
        g.addWidget(QLabel("HP Quick Adjust"), 8, 0)
        quick = QHBoxLayout()
        for txt,val in [("-5",-5),("-1",-1),("+1",+1),("+5",+5)]:
            b=QPushButton(txt); b.clicked.connect(lambda _,v=val:self.bump_hp(v))
            quick.addWidget(b)
        wrap = QWidget(); wrap.setLayout(quick); g.addWidget(wrap, 8, 1)

    # ----- UI: active combatants table
    def _build_combat_table(self):
        self.table_panel = QGroupBox("Active Combatants", objectName="combat_table")
        v = QVBoxLayout(self.table_panel)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Turn","Name","Init Roll","Mod","FX","Type"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        v.addWidget(self.table)

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

    def refresh_party(self):
        self.listbox.clear()
        for m in self.party_view_sorted():
            tag = "[E]" if m.isEnemy else "[P]"
            self.listbox.addItem(QListWidgetItem(f"{tag} {m.name}  (Init:{m.turnOrder or 0}  Mod:{m.initMod:+})"))

    def refresh_table(self):
        self.table.setRowCount(0)
        for m in self.party_view_sorted():
            row = self.table.rowCount(); self.table.insertRow(row)
            fx = " ".join(STATUS_EMOJI.get(s.lower(), s[:1].upper()) for s in (m.statusEffects or []))
            vals = [m.turnOrder or 0, m.name, m.initiative if m.initiative is not None else "",
                    f"{m.initMod:+}", fx, "Enemy" if m.isEnemy else "Player"]
            for c,val in enumerate(vals):
                self.table.setItem(row, c, QTableWidgetItem(str(val)))

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

    def add_member_clear(self):
        self.listbox.clearSelection()
        self.ent_name.clear(); self.ent_icon.clear()
        self.spn_max.setValue(0); self.spn_cur.setValue(0); self.spn_mod.setValue(0)
        self.chk_enemy.setChecked(False)

    def remove_member(self):
        idx = self._current_index()
        if idx is None: return
        m = self.store.party[idx]
        if QMessageBox.question(self, "Remove", f"Remove {m.name}?") != QMessageBox.Yes: return
        del self.store.party[idx]
        self.store.save_party()
        if self.store.config.get("turnIndex",0) >= len(self.store.party):
            self.store.config["turnIndex"] = max(0, len(self.store.party)-1)
            self.store.save_config()
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
        idx = self._current_index()

        if idx is None:
            m = PartyMember(name=name, maxHP=maxhp, currentHP=curhp, isEnemy=is_enemy)
            self.store.party.append(m)
            idx = len(self.store.party)-1
        m = self.store.party[idx]
        m.name=name; m.maxHP=maxhp; m.currentHP=curhp; m.isEnemy=is_enemy; m.initMod=initmod
        icon_src = self.ent_icon.text().strip()
        if icon_src:
            rel = process_icon_to_gray(Path(icon_src), name)
            if rel: m.icon=rel
        if m.statusEffects is None: m.statusEffects=[]

        self.store.save_party()
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
            QMessageBox.information(self, "Statuses", "Select a character first."); return
        m = self.store.party[idx]
        dlg = StatusPopup(self, m.statusEffects or [])
        if dlg.exec() == QDialog.Accepted:
            m.statusEffects = dlg.selected()
            self.store.save_party()
            self.refresh_table()

    def show_legend(self):
        StatusLegend(self).exec()

    # ----- combat control -----
    def _combat_text(self)->str:
        return "Combat: ON" if self.store.config.get("combat_mode", False) else "Combat: OFF"

    def ensure_initiatives(self):
        for m in self.store.party:
            if m.initiative is None:
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
        n=len(self.store.party)
        if n==0: return
        self.store.config["turnIndex"] = (self.store.config.get("turnIndex",0)+1) % n
        self.store.save_config()

    def prev_turn(self):
        n=len(self.store.party)
        if n==0: return
        self.store.config["turnIndex"] = (self.store.config.get("turnIndex",0)-1) % n
        self.store.save_config()

    def next_dialog(self):
        self.store.config["dialogIndex"] = self.store.config.get("dialogIndex",0) + 1
        self.store.save_config()

    def prev_dialog(self):
        self.store.config["dialogIndex"] = max(0, self.store.config.get("dialogIndex",0)-1)
        self.store.save_config()

    # ----- overlay -----
    def launch_overlay(self, normal=True):
        """Launch tracker_overlay.py; if it fails immediately, offer Debug Mode."""
        try:
            if not OVERLAY_PY.exists():
                raise FileNotFoundError(f"{OVERLAY_PY} not found")
            # try pythonw on Windows for clean launch
            py = Path(sys.executable)
            if os.name == "nt":
                pyw = py.with_name("pythonw.exe")
                exe = str(pyw if pyw.exists() else py)
            else:
                exe = str(py)

            # start and wait a moment to detect immediate crash
            proc = subprocess.Popen([exe, str(OVERLAY_PY)], cwd=str(APP_DIR))
            try:
                proc.wait(timeout=1)
            except Exception:
                pass
            if proc.poll() not in (None, 0):
                raise RuntimeError("Overlay exited on startup.")
        except Exception as e:
            if QMessageBox.question(self, "Overlay Launch Failed",
                                    f"{e}\n\nLaunch in Debug Mode to see errors?",
                                    QMessageBox.Yes|QMessageBox.No) == QMessageBox.Yes:
                subprocess.Popen([sys.executable, str(OVERLAY_PY), "--debug"], cwd=str(APP_DIR))

    def stop_overlay(self):
        QMessageBox.information(self, "Overlay", "Close the overlay window manually.")

    # ----- file I/O -----
    def reload_files(self):
        self.store.party = self.store.load_party()
        self.store.config = self.store.load_config()
        self.current_theme = self.store.config.get("theme", "gm-modern")
        self.theme.load_theme(self.current_theme)
        self.host.relayout()
        self.btn_combat.setText(self._combat_text())
        self.refresh_party(); self.refresh_table()

    def save_all(self):
        self.store.save_party(); self.store.save_config()
        QMessageBox.information(self, "Saved", "party.json and config.json saved.")


def main():
    app = QApplication(sys.argv)
    win = GMWindow()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
