# gm_ui.py — EncounterOS GM UI (refreshed)
from __future__ import annotations
import json, os
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime, timezone

from PySide6 import QtWidgets, QtGui, QtCore

APP_DIR    = Path(__file__).resolve().parent
PARTY_FP   = APP_DIR/"party.json"
CONFIG_FP  = APP_DIR/"config.json"
DIALOG_FP  = APP_DIR/"dialog.txt"
DIALOGMETA = APP_DIR/"dialog_meta.json"
THEMES_DIR = APP_DIR/"themes"
STATUS_DIR = APP_DIR/"icons"/"status"

# Encounters storage
DATA_ROOT  = APP_DIR/"data"/"encounters"
COMBAT_DIR = DATA_ROOT/"combat"
DIALOG_DIR = DATA_ROOT/"dialog"
COMBAT_DIR.mkdir(parents=True, exist_ok=True)
DIALOG_DIR.mkdir(parents=True, exist_ok=True)

# Log + Notes (vault)
LOG_DIR = APP_DIR / "data"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "session.log"

VAULT_DIR  = APP_DIR / "data" / "notes"
VAULT_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_NOTE = VAULT_DIR / "notes.md"

# ---------- helpers ----------
def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

def _slug(s: str) -> str:
    return "-".join((s or "").strip().lower().split())

def safe_json(path: Path, default):
    try: return json.loads(path.read_text(encoding="utf-8"))
    except Exception: return default

def write_json(path: Path, data: dict):
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

def write_dialog_txt(blocks: List[str]):
    text = "\n\n".join(b.strip() for b in blocks if b.strip())
    DIALOG_FP.write_text(text, encoding="utf-8")

# ---------- GM UI light/dark ----------
DARK_QSS = """
QWidget { background-color: #1d1f23; color: #e6e6e6; }
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox, QListWidget {
  background-color: #2a2d33; color:#e6e6e6; border:1px solid #3a3f47;
}
QPushButton { background-color:#2f343c; border:1px solid #444; padding:4px 8px; }
QPushButton:hover { background-color:#3a4049; }
QTabBar::tab { background:#2a2d33; padding:6px 10px; border:1px solid #3a3f47; }
QTabBar::tab:selected { background:#3a3f47; }
QToolTip { background:#2a2d33; color:#e6e6e6; border:1px solid #3a3f47; }
QGroupBox { border:1px solid #3a3f47; margin-top: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid #888; background: #222; }
QCheckBox::indicator:checked { image: none; background: #4a9cff; border: 1px solid #4a9cff; }
"""

LIGHT_QSS = """
QWidget { background-color: #fafafa; color: #101010; }
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox, QListWidget {
  background-color: #ffffff; color:#101010; border:1px solid #cfcfcf;
}
QPushButton { background-color:#f1f1f1; border:1px solid #cfcfcf; padding:4px 8px; }
QPushButton:hover { background-color:#e9e9e9; }
QTabBar::tab { background:#ffffff; padding:6px 10px; border:1px solid #cfcfcf; }
QTabBar::tab:selected { background:#e9e9e9; }
QToolTip { background:#ffffff; color:#101010; border:1px solid #cfcfcf; }
QGroupBox { border:1px solid #cfcfcf; margin-top: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid #aaa; background: #fff; }
QCheckBox::indicator:checked { image: none; background: #2b7de9; border: 1px solid #2b7de9; }
"""

# ---------- main window ----------
class GMWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EncounterOS — GM")
        self.resize(1220, 820)

        cfg0 = safe_json(CONFIG_FP, {})
        self.theme_name   = cfg0.get("theme", "gm-modern")
        self.auto_refresh = bool(cfg0.get("auto_refresh", True))
        self.poll_ms      = max(100, int(cfg0.get("poll_ms", 200)))
        self.ui_dark      = bool(cfg0.get("ui_dark", True))

        self.mode = "combat"   # "combat" | "dialog"
        self.overlay_on = False

        # Live models
        self.combatants: List[Dict] = []
        self.turn_index: int = -1
        self.round: int = 1

        self.dialog_blocks: List[Dict] = []
        self.dialog_index: int = -1
        self._dialog_edit_row: Optional[int] = None

        self._status_catalog = self._load_status_catalog()

        # Menubar + topbar
        self._build_menubar()
        self._build_topbar()

        # Split main area
        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self._left_cockpit = self._build_mvp_cockpit()
        self._right_dock   = self._build_advanced_dock()
        split.addWidget(self._left_cockpit)
        split.addWidget(self._right_dock)
        split.setStretchFactor(0, 7)
        split.setStretchFactor(1, 3)

        w = QtWidgets.QWidget(); v = QtWidgets.QVBoxLayout(w)
        v.setContentsMargins(0,0,0,0)
        v.addWidget(self.topbar)
        v.addWidget(split)
        self.setCentralWidget(w)

        self._apply_ui_theme(self.ui_dark)

        # Shortcuts
        QtGui.QShortcut(QtGui.QKeySequence("F4"), self, activated=self._toggle_overlay_hotkey)
        QtGui.QShortcut(QtGui.QKeySequence("F5"), self, activated=self._advance)  # context: combat/dialog
        QtGui.QShortcut(QtGui.QKeySequence("F7"), self, activated=self._prev)
        QtGui.QShortcut(QtGui.QKeySequence("F6"), self, activated=self._toggle_mode)
        QtGui.QShortcut(QtGui.QKeySequence("/"),  self, activated=self._focus_active_search)
        QtGui.QShortcut(QtGui.QKeySequence("Ctrl+Return"), self, activated=self._add_dialog_block)
        QtGui.QShortcut(QtGui.QKeySequence("F8"), self, activated=self._dialog_make_current)  # explicit push live

        # Overlay link
        self.overlay_win: Optional[QtWidgets.QWidget] = None
        try:
            import importlib
            mod = importlib.import_module("tracker_overlay")
            self._OverlayClass = getattr(mod, "Overlay", None) if hasattr(mod, "Overlay") else None
        except Exception as e:
            print("[gm_ui] tracker_overlay import problem:", e)
            self._OverlayClass = None

        # initial write
        self._sync_topbar()
        self._persist_all()

    # ---------- Menus / topbar ----------
    def _build_menubar(self):
        mb = self.menuBar()
        # File
        mFile = mb.addMenu("&File")
        actOpenThemes = mFile.addAction("Open Themes Folder")
        actOpenThemes.triggered.connect(lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(THEMES_DIR))))
        actOpenEnc = mFile.addAction("Open Encounters Folder")
        actOpenEnc.triggered.connect(lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(DATA_ROOT))))
        actOpenNotes = mFile.addAction("Open Notes Folder")
        actOpenNotes.triggered.connect(lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(VAULT_DIR))))
        mFile.addSeparator()
        actExit = mFile.addAction("Exit"); actExit.triggered.connect(self.close)

        # View
        mView = mb.addMenu("&View")
        self.actDarkMode = mView.addAction("Dark Mode")
        self.actDarkMode.setCheckable(True)
        self.actDarkMode.setChecked(self.ui_dark)
        self.actDarkMode.toggled.connect(self._toggle_ui_dark)

        # Overlay
        mOverlay = mb.addMenu("&Overlay")
        actReload = mOverlay.addAction("Reload Now")
        actReload.triggered.connect(self._reload_now)

        self.actAutoRefresh = mOverlay.addAction("Auto Refresh")
        self.actAutoRefresh.setCheckable(True)
        self.actAutoRefresh.setChecked(self.auto_refresh)
        self.actAutoRefresh.toggled.connect(self._set_auto_refresh)

        actInterval = mOverlay.addAction("Set Refresh Interval…")
        actInterval.triggered.connect(self._set_poll_interval)

        self._themes_menu = mOverlay.addMenu("Theme")
        self._populate_themes_menu()

    def _build_topbar(self):
        self.topbar = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(self.topbar); h.setContentsMargins(8,8,8,8); h.setSpacing(12)
        self.btnOverlay = QtWidgets.QToolButton()
        self.btnOverlay.setText("Overlay OFF"); self.btnOverlay.setCheckable(True)
        self.btnOverlay.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.btnOverlay.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_ComputerIcon))
        self.btnOverlay.toggled.connect(self._set_overlay)
        h.addWidget(self.btnOverlay)

        self.btnMode = QtWidgets.QToolButton()
        self.btnMode.setCheckable(True); self.btnMode.setChecked(True)
        self.btnMode.toggled.connect(self._mode_button_toggled)
        self._update_mode_button_text()
        h.addWidget(self.btnMode)

        self.cmbTheme = QtWidgets.QComboBox(); self.cmbTheme.setMinimumWidth(180)
        self._populate_themes_combo()
        if self.theme_name in [self.cmbTheme.itemText(i) for i in range(self.cmbTheme.count())]:
            self.cmbTheme.setCurrentText(self.theme_name)
        self.cmbTheme.currentTextChanged.connect(self._set_theme_from_combo)
        h.addWidget(self.cmbTheme)
        h.addStretch(1)

    def _populate_themes_combo(self):
        self.cmbTheme.clear()
        names=[]
        try:
            if THEMES_DIR.exists():
                for p in sorted(THEMES_DIR.iterdir()):
                    if p.is_dir() and (p/"theme.json").exists(): names.append(p.name)
        except Exception: pass
        if not names:
            names = [self.theme_name] if self.theme_name else ["gm-modern"]
        self.cmbTheme.addItems(names)

    def _populate_themes_menu(self):
        self._themes_menu.clear()
        names=[]
        try:
            if THEMES_DIR.exists():
                for p in sorted(THEMES_DIR.iterdir()):
                    if p.is_dir() and (p/"theme.json").exists(): names.append(p.name)
        except Exception: pass
        if not names:
            names = [self.theme_name] if self.theme_name else ["gm-modern"]
        group = QtGui.QActionGroup(self); group.setExclusive(True)
        for n in names:
            act = self._themes_menu.addAction(n); act.setCheckable(True)
            act.setChecked(n == self.theme_name)
            act.triggered.connect(lambda checked, s=n: self.cmbTheme.setCurrentText(s))
            group.addAction(act)

    def _set_theme_from_combo(self, name: str):
        if not name: return
        self.theme_name = name.strip()
        self._persist_config()
        for act in self._themes_menu.actions():
            act.setChecked(act.text() == name)
        self._toast(f"Overlay theme set to '{name}'.")

    def _update_mode_button_text(self):
        self.btnMode.setText(f"Mode: {'Combat' if self.btnMode.isChecked() else 'Dialog'}")

    def _mode_button_toggled(self, checked: bool):
        self.mode = "combat" if checked else "dialog"
        self._update_mode_button_text()
        self._persist_config()
        self._toast(f"Mode → {self.mode.capitalize()}")

    def _set_overlay(self, on: bool):
        self.overlay_on = on
        self.btnOverlay.setText("Overlay ON" if on else "Overlay OFF")
        if on and hasattr(self, "_OverlayClass") and self._OverlayClass:
            if not self.overlay_win:
                self.overlay_win = self._OverlayClass()
            self.overlay_win.show(); self._center_on_screen(self.overlay_win)
        elif self.overlay_win:
            self.overlay_win.hide()

    def _toggle_overlay_hotkey(self):
        self.btnOverlay.setChecked(not self.btnOverlay.isChecked())

    def _reload_now(self):
        self._persist_config()
        self._toast("Requested overlay reload.")

    def _set_auto_refresh(self, on: bool):
        self.auto_refresh = bool(on)
        self._persist_config()
        self._toast(f"Auto-refresh {'ON' if on else 'OFF'}.")

    def _set_poll_interval(self):
        # Positional args only (PySide6 compat)
        ms, ok = QtWidgets.QInputDialog.getInt(self, "Refresh Interval",
                                               "Milliseconds (>=100):",
                                               int(self.poll_ms), 100, 60000, 100)
        if not ok: return
        self.poll_ms = int(ms)
        self._persist_config()
        self._toast(f"Refresh interval set to {self.poll_ms} ms.")

    def _toggle_ui_dark(self, on: bool):
        self.ui_dark = bool(on)
        self._apply_ui_theme(self.ui_dark)
        self._persist_config()

    def _apply_ui_theme(self, dark: bool):
        self.setStyleSheet(DARK_QSS if dark else LIGHT_QSS)

    def _sync_topbar(self):
        if hasattr(self, "btnOverlay"):
            self.btnOverlay.setChecked(self.overlay_on)
        if hasattr(self, "btnMode"):
            self.btnMode.setChecked(self.mode == "combat")
            self._update_mode_button_text()
        if hasattr(self, "cmbTheme"):
            idx = self.cmbTheme.findText(self.theme_name)
            if idx >= 0:
                old = self.cmbTheme.blockSignals(True)
                self.cmbTheme.setCurrentIndex(idx)
                self.cmbTheme.blockSignals(old)
        if hasattr(self, "actDarkMode"):
            old = self.actDarkMode.blockSignals(True)
            self.actDarkMode.setChecked(self.ui_dark)
            self.actDarkMode.blockSignals(old)
        if hasattr(self, "actAutoRefresh"):
            old = self.actAutoRefresh.blockSignals(True)
            self.actAutoRefresh.setChecked(self.auto_refresh)
            self.actAutoRefresh.blockSignals(old)
        self._populate_themes_menu()

    # ---------- MVP cockpit ----------
    def _build_mvp_cockpit(self) -> QtWidgets.QWidget:
        panel = QtWidgets.QWidget(); v = QtWidgets.QVBoxLayout(panel)
        v.setContentsMargins(8,8,8,8); v.setSpacing(8)

        # Combat
        self.grpCombat = QtWidgets.QGroupBox("Combat Controls")
        self.grpCombat.setCheckable(False)
        cv = QtWidgets.QVBoxLayout(self.grpCombat); cv.setSpacing(8)

        rowHud = QtWidgets.QHBoxLayout()
        self.lblTurn = QtWidgets.QLabel("Round 1 • Turn: —")
        rowHud.addWidget(self.lblTurn, 1)
        self.btnPrev = QtWidgets.QPushButton("⟵ Prev (F7)")
        self.btnAdvance = QtWidgets.QPushButton("▶ Advance (F5)")
        self.btnPrev.clicked.connect(self._advance_combat_prev)
        self.btnAdvance.clicked.connect(self._advance_combat_next)
        rowHud.addWidget(self.btnPrev); rowHud.addWidget(self.btnAdvance)
        cv.addLayout(rowHud)

        self.listCombat = QtWidgets.QListWidget()
        self.listCombat.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.listCombat.setUniformItemSizes(True)
        self.listCombat.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        self.listCombat.currentRowChanged.connect(self._on_combat_selection_changed)
        self.listCombat.itemDoubleClicked.connect(lambda _: self._edit_selected())
        cv.addWidget(self.listCombat, 1)

        grpHP = QtWidgets.QGroupBox("Selected"); gl = QtWidgets.QGridLayout(grpHP)
        self.lblSelName = QtWidgets.QLabel("—")
        gl.addWidget(self.lblSelName, 0, 0, 1, 6)
        self.btnHPm5 = QtWidgets.QPushButton("−5"); self.btnHPm1 = QtWidgets.QPushButton("−1")
        self.btnHPp1 = QtWidgets.QPushButton("+1"); self.btnHPp5 = QtWidgets.QPushButton("+5")
        self.btnHPSet= QtWidgets.QPushButton("Set…"); self.btnStatus = QtWidgets.QPushButton("Status…")
        gl.addWidget(self.btnHPm5,1,0); gl.addWidget(self.btnHPm1,1,1); gl.addWidget(self.btnHPp1,1,2)
        gl.addWidget(self.btnHPp5,1,3); gl.addWidget(self.btnHPSet,1,4); gl.addWidget(self.btnStatus,1,5)
        cv.addWidget(grpHP)

        rowInit = QtWidgets.QHBoxLayout()
        self.btnAddSingle = QtWidgets.QPushButton("Add…")
        self.btnEdit = QtWidgets.QPushButton("Edit Selected")
        self.btnRemove = QtWidgets.QPushButton("Remove (Del)")
        self.btnDup = QtWidgets.QPushButton("Duplicate Selected"); self.btnDup.setMaximumWidth(180)
        self.btnClear = QtWidgets.QPushButton("Clear")
        rowInit.addWidget(self.btnAddSingle); rowInit.addWidget(self.btnEdit); rowInit.addWidget(self.btnRemove)
        rowInit.addWidget(self.btnDup); rowInit.addWidget(self.btnClear); rowInit.addStretch(1)
        cv.addLayout(rowInit)

        self.searchCombat = QtWidgets.QLineEdit()
        self.searchCombat.setPlaceholderText("Quick add by name (Enter adds +1)")
        cv.addWidget(self.searchCombat)

        v.addWidget(self.grpCombat)

        # Dialog
        self.grpDialog = QtWidgets.QGroupBox("Dialog Controls")
        self.grpDialog.setCheckable(False)
        dv = QtWidgets.QVBoxLayout(self.grpDialog); dv.setSpacing(8)

        rowDlgHud = QtWidgets.QHBoxLayout()
        self.lblDialogHud = QtWidgets.QLabel("0 / 0 — Speaker: —")
        rowDlgHud.addWidget(self.lblDialogHud, 1)
        self.btnDlgPrev = QtWidgets.QPushButton("⟵ Prev")
        self.btnDlgNext = QtWidgets.QPushButton("▶ Advance")
        self.btnDlgMakeCur = QtWidgets.QPushButton("Make Current ▶")
        self.btnDlgPrev.clicked.connect(self._dialog_prev_local)
        self.btnDlgNext.clicked.connect(self._dialog_next_local)
        self.btnDlgMakeCur.clicked.connect(self._dialog_make_current)
        rowDlgHud.addWidget(self.btnDlgPrev); rowDlgHud.addWidget(self.btnDlgNext); rowDlgHud.addWidget(self.btnDlgMakeCur)
        dv.addLayout(rowDlgHud)

        self.listDialog = QtWidgets.QListWidget()
        self.listDialog.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.listDialog.setUniformItemSizes(True)
        self.listDialog.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        self.listDialog.currentRowChanged.connect(self._on_dialog_row_changed)
        dv.addWidget(self.listDialog, 1)

        form = QtWidgets.QFormLayout()
        self.edSpeaker = QtWidgets.QLineEdit(); self.edSpeaker.setPlaceholderText("Speaker (optional)")
        self.edText    = QtWidgets.QPlainTextEdit(); self.edText.setPlaceholderText("Type dialog… (blank line = new block)")
        prow = QtWidgets.QHBoxLayout()
        self.edPortrait = QtWidgets.QLineEdit(); self.edPortrait.setPlaceholderText("Portrait PNG (optional)")
        self.btnPickPortrait = QtWidgets.QPushButton("Choose Portrait…"); self.btnPickPortrait.clicked.connect(self._pick_dialog_portrait)
        prow.addWidget(self.edPortrait, 1); prow.addWidget(self.btnPickPortrait)
        form.addRow("Speaker", self.edSpeaker)
        form.addRow("Text", self.edText)
        form.addRow("Portrait", prow)
        dv.addLayout(form)

        rowDlgOps = QtWidgets.QHBoxLayout()
        self.btnAddDialog = QtWidgets.QPushButton("Add to Queue (Ctrl+Enter)")
        self.btnNewDialog = QtWidgets.QPushButton("New Block")
        self.btnDlgRemove = QtWidgets.QPushButton("Remove (Del)")
        self.btnDlgClear  = QtWidgets.QPushButton("Clear")
        rowDlgOps.addWidget(self.btnAddDialog); rowDlgOps.addWidget(self.btnNewDialog)
        rowDlgOps.addWidget(self.btnDlgRemove); rowDlgOps.addWidget(self.btnDlgClear); rowDlgOps.addStretch(1)
        dv.addLayout(rowDlgOps)

        v.addWidget(self.grpDialog)

        # Wire combat
        self.btnHPm5.clicked.connect(lambda: self._nudge_hp(-5))
        self.btnHPm1.clicked.connect(lambda: self._nudge_hp(-1))
        self.btnHPp1.clicked.connect(lambda: self._nudge_hp(+1))
        self.btnHPp5.clicked.connect(lambda: self._nudge_hp(+5))
        self.btnHPSet.clicked.connect(self._set_hp)
        self.btnStatus.clicked.connect(self._open_status_editor)

        self.btnAddSingle.clicked.connect(self._add_single)
        self.btnEdit.clicked.connect(self._edit_selected)
        self.btnRemove.clicked.connect(self._remove_selected)
        self.btnDup.clicked.connect(self._duplicate_selected)
        self.btnClear.clicked.connect(self._clear_combat)
        self.searchCombat.returnPressed.connect(lambda: self._add_from_search(1))
        QtGui.QShortcut(QtGui.QKeySequence("Delete"), self.grpCombat, activated=self._remove_selected)

        # Wire dialog
        self.btnAddDialog.clicked.connect(self._add_dialog_block)
        self.btnNewDialog.clicked.connect(self._new_dialog_block)
        self.btnDlgRemove.clicked.connect(self._remove_selected_dialog)
        self.btnDlgClear.clicked.connect(self._clear_dialog)
        QtGui.QShortcut(QtGui.QKeySequence("Delete"), self.grpDialog, activated=self._remove_selected_dialog)

        return panel

    def _build_advanced_dock(self) -> QtWidgets.QWidget:
        tabs = QtWidgets.QTabWidget()
        self._build_encounters_tab(tabs)
        self._build_log_tab(tabs)
        self._build_settings_tab(tabs)
        self._build_notes_tab(tabs)
        return tabs

    # ---------- Combat logic ----------
    def _status_emojis(self, statuses):
        MAP = {
            "poisoned":"☠️", "stunned":"💫", "prone":"🛌", "blessed":"✨",
            "charmed":"💖", "grappled":"🤝", "frightened":"😱", "invisible":"👻",
            "blinded":"🕶️", "deafened":"🔇", "paralyzed":"🧊", "restrained":"⛓️",
            "burning":"🔥", "bleeding":"🩸"
        }
        out=[]
        for s in (statuses or []):
            key=str(s).strip().lower()
            if not key: continue
            out.append(MAP.get(key, key[:1].upper()))
            if len(out)>=3: break
        return " " + " ".join(out) if out else ""

    def _combat_row_text(self, m: dict) -> str:
        name = m.get("name","?")
        cur = m.get("currentHP","?")
        mx  = m.get("maxHP","?")
        init= int(m.get("initiative",0))
        badges = self._status_emojis(m.get("statusEffects"))
        return f"{name}   HP {cur}/{mx}   Init {init:+d}{badges}"

    def _refresh_combat_list(self):
        cur_rows = [i.row() for i in self.listCombat.selectedIndexes()]
        vbar = self.listCombat.verticalScrollBar(); vpos = vbar.value() if vbar else 0

        self.listCombat.clear()
        for m in self.combatants:
            QtWidgets.QListWidgetItem(self._combat_row_text(m), self.listCombat)

        if self.combatants:
            if self.turn_index < 0 or self.turn_index >= len(self.combatants):
                self.turn_index = 0
        else:
            self.turn_index = -1; self.round = 1

        if cur_rows:
            for r in cur_rows:
                if 0 <= r < self.listCombat.count():
                    self.listCombat.item(r).setSelected(True)
            if 0 <= cur_rows[0] < self.listCombat.count():
                self.listCombat.setCurrentRow(cur_rows[0])
        if vbar:
            QtCore.QTimer.singleShot(0, lambda: vbar.setValue(vpos))

        self._update_turn_label()
        self._on_combat_selection_changed(self.listCombat.currentRow())

    def _update_turn_label(self):
        if 0 <= self.turn_index < len(self.combatants):
            self.lblTurn.setText(f"Round {self.round} • Turn: {self.combatants[self.turn_index]['name']}")
        else:
            self.lblTurn.setText(f"Round {self.round} • Turn: —")

    def _on_combat_selection_changed(self, row: int):
        if 0 <= row < len(self.combatants):
            m = self.combatants[row]
            self.lblSelName.setText(f"{m['name']}  HP {m.get('currentHP','?')}/{m.get('maxHP','?')}")
        else:
            self.lblSelName.setText("—")

    def _update_combat_row(self, row: int):
        if row < 0 or row >= len(self.combatants):
            self._on_combat_selection_changed(-1); return
        m = self.combatants[row]
        self._on_combat_selection_changed(row)
        item = self.listCombat.item(row)
        if item: item.setText(self._combat_row_text(m))

    def _nudge_hp(self, delta: int):
        rows = [i.row() for i in self.listCombat.selectedIndexes()]
        if not rows: return
        row = rows[0]; m = self.combatants[row]
        maxhp = max(1, int(m.get("maxHP",1)))
        cur = max(0, min(maxhp, int(m.get("currentHP",maxhp)) + int(delta)))
        m["currentHP"] = cur
        self._update_combat_row(row); self._persist_party()
        self._log(f"{m['name']}: HP {delta:+d} → {cur}/{maxhp}")

    def _set_hp(self):
        rows = [i.row() for i in self.listCombat.selectedIndexes()]
        if not rows: return
        row = rows[0]; m = self.combatants[row]
        cur = int(m.get("currentHP", m.get("maxHP", 10)))
        maxhp = int(m.get("maxHP", 10))
        val, ok = QtWidgets.QInputDialog.getInt(self, "Set HP", f"Current / Max ({maxhp}):", cur, 0, maxhp, 1)
        if not ok: return
        m["currentHP"] = int(val)
        self._update_combat_row(row); self._persist_party()
        self._log(f"{m['name']}: HP set → {int(val)}/{maxhp}")

    def _open_status_editor(self):
        rows = [i.row() for i in self.listCombat.selectedIndexes()]
        if not rows: return
        row = rows[0]; m = self.combatants[row]
        current = set([s for s in (m.get("statusEffects") or []) if isinstance(s,str)])

        dlg = QtWidgets.QDialog(self); dlg.setWindowTitle(f"Status — {m.get('name','')}")
        v = QtWidgets.QVBoxLayout(dlg)
        scroll = QtWidgets.QScrollArea(); scroll.setWidgetResizable(True)
        inner = QtWidgets.QWidget(); iv = QtWidgets.QVBoxLayout(inner)
        checks = []
        for name in self._status_catalog:
            cb = QtWidgets.QCheckBox(name)
            cb.setChecked(name in current)
            iv.addWidget(cb); checks.append(cb)
        iv.addStretch(1); inner.setLayout(iv); scroll.setWidget(inner)
        v.addWidget(scroll, 1)
        box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok|QtWidgets.QDialogButtonBox.Cancel)
        v.addWidget(box); box.accepted.connect(dlg.accept); box.rejected.connect(dlg.reject)

        if dlg.exec() == QtWidgets.QDialog.Accepted:
            chosen = [cb.text() for cb in checks if cb.isChecked()]
            m["statusEffects"] = chosen
            self._update_combat_row(row); self._persist_party()
            self._log(f"{m['name']}: Status → {', '.join(chosen) if chosen else 'none'}")

    def _advance_combat_next(self):
        if not self.combatants: return
        self.turn_index = (self.turn_index + 1) % len(self.combatants)
        if self.turn_index == 0: self.round += 1
        self._update_turn_label(); self._persist_config()
        self._log(f"Turn → {self.combatants[self.turn_index]['name']} (Round {self.round})")

    def _advance_combat_prev(self):
        if not self.combatants: return
        self.turn_index = (self.turn_index - 1) % len(self.combatants)
        self._update_turn_label(); self._persist_config()
        self._log(f"Turn → {self.combatants[self.turn_index]['name']} (Round {self.round})")

    def _add_single(self):
        dlg = _CombatantEditor(self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            p = dlg.payload()
            base = {"name": p["name"], "isEnemy": (p["side"]=="opponents"),
                    "maxHP": p["hpmax"], "currentHP": p["hpmax"], "icon": p.get("portrait",""),
                    "statusEffects": [], "initiative": p["initiative"]}
            self._add_instances(base, 1); self._persist_party()

    def _edit_selected(self):
        rows = [i.row() for i in self.listCombat.selectedIndexes()]
        if not rows: return
        row = rows[0]; data = dict(self.combatants[row])
        dlg = _CombatantEditor(self, data)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        p = dlg.payload()
        m = self.combatants[row]
        m["name"] = p["name"]
        m["isEnemy"] = (p["side"] == "opponents")
        m["maxHP"] = int(p["hpmax"])
        m["currentHP"] = min(int(m.get("currentHP", p["hpmax"])), int(p["hpmax"]))
        m["icon"] = p.get("portrait","")
        m["initiative"] = int(p["initiative"])
        self._update_combat_row(row); self._persist_party()

    def _duplicate_selected(self):
        rows = sorted({i.row() for i in self.listCombat.selectedIndexes()})
        if not rows: return
        for r in rows:
            base = dict(self.combatants[r])
            base["name"] = base["name"].split(" ")[0]
            self._add_instances(base, 1)
        self._persist_party()
        self._log(f"Duplicated {len(rows)} combatant(s)")

    def _remove_selected(self):
        rows = sorted({i.row() for i in self.listCombat.selectedIndexes()}, reverse=True)
        if not rows: return
        for r in rows:
            if 0 <= r < len(self.combatants):
                del self.combatants[r]
        if not self.combatants:
            self.turn_index = -1; self.round = 1
        else:
            self.turn_index = min(self.turn_index, len(self.combatants) - 1)
        self._refresh_combat_list(); self._persist_party()
        self._log(f"Removed {len(rows)} combatant(s)")

    def _clear_combat(self):
        if not self.combatants: return
        self.combatants.clear(); self.turn_index = -1; self.round = 1
        self._refresh_combat_list(); self._persist_party()
        self._log("Cleared combat")

    def _add_from_search(self, count: int):
        q = self.searchCombat.text().strip()
        if not q: return
        base = {"name": q, "isEnemy": True, "maxHP": 10, "currentHP": 10, "icon": "", "statusEffects": [], "initiative": 0}
        self._add_instances(base, count); self._persist_party()

    def _add_instances(self, base: Dict, count: int):
        base_name = base["name"]
        current_names = [c["name"] for c in self.combatants]

        def _is_base_match(n: str) -> bool:
            return (n == base_name) or n.startswith(base_name + " ")

        existing_idxs = [i for i, n in enumerate(current_names) if _is_base_match(n)]
        total_after = len(existing_idxs) + count

        if len(existing_idxs) == 1 and total_after >= 2:
            idx = existing_idxs[0]
            if self.combatants[idx]["name"] == base_name:
                self.combatants[idx]["name"] = f"{base_name} A"

        current_names = [c["name"] for c in self.combatants]
        used = _collect_suffixes(base_name, current_names)

        for _ in range(max(1, count)):
            if total_after == 1 and len(existing_idxs) == 0:
                name = base_name
            else:
                suf = _next_suffix(used); used.add(suf)
                name = f"{base_name} {suf}"
            inst = dict(base); inst["name"] = name
            self.combatants.append(inst)

        if self.turn_index < 0 and self.combatants: self.turn_index = 0
        self._refresh_combat_list()
        self._log(f"Added {count} × {base_name.split(' ')[0]}")

    # ---------- Dialog logic ----------
    def _dialog_prev_local(self):
        if not self.dialog_blocks:
            return
        if self.dialog_index < 0:
            self.dialog_index = 0
        else:
            self.dialog_index = max(self.dialog_index - 1, 0)
        self._persist_config()
        self._highlight_dialog_current()
        self._update_dialog_hud()
        self._log(f"Dialog ← {self.dialog_index+1}/{len(self.dialog_blocks)}")

    def _dialog_next_local(self):
        if not self.dialog_blocks:
            return
        if self.dialog_index < 0:
            self.dialog_index = 0
        else:
            self.dialog_index = min(self.dialog_index + 1, len(self.dialog_blocks) - 1)
        self._persist_config()
        self._highlight_dialog_current()
        self._update_dialog_hud()
        self._log(f"Dialog → {self.dialog_index+1}/{len(self.dialog_blocks)}")

    def _dialog_make_current(self):
        row = self.listDialog.currentRow()
        if row < 0 or row >= len(self.dialog_blocks):
            return
        self.dialog_index = row
        self._persist_config()
        self._highlight_dialog_current()
        self._update_dialog_hud()
        self._log(f"Dialog → set current to {self.dialog_index+1}/{len(self.dialog_blocks)}")

    def _new_dialog_block(self):
        self._dialog_edit_row = None
        self._clear_dialog_editor_fields()
        self.btnAddDialog.setText("Add to Queue (Ctrl+Enter)")
        self.listDialog.clearSelection()

    def _on_dialog_row_changed(self, row: int):
        # Selection is for editing only — does not change live overlay
        if row < 0 or row >= len(self.dialog_blocks):
            self._dialog_edit_row = None
            self._clear_dialog_editor_fields()
            self.btnAddDialog.setText("Add to Queue (Ctrl+Enter)")
            self._update_dialog_hud()
            return

        self._dialog_edit_row = row
        b = self.dialog_blocks[row]
        self.edSpeaker.setText(b.get("speaker",""))
        self.edText.setPlainText(b.get("text",""))
        self.edPortrait.setText(b.get("portrait",""))
        self.btnAddDialog.setText("Save Changes (Ctrl+Enter)")
        self._update_dialog_hud()

    def _clear_dialog_editor_fields(self):
        self.edSpeaker.clear(); self.edText.clear(); self.edPortrait.clear()

    def _pick_dialog_portrait(self):
        p, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Portrait", "", "Images (*.png *.jpg *.jpeg *.webp)")
        if p:
            try: self.edPortrait.setText(str(Path(p).resolve().relative_to(APP_DIR)))
            except Exception: self.edPortrait.setText(p)

    def _add_dialog_block(self):
        speaker  = self.edSpeaker.text().strip()
        raw_text = self.edText.toPlainText().strip()
        portrait = self.edPortrait.text().strip()
        if not raw_text: return

        if self._dialog_edit_row is not None:
            blk = {"speaker": speaker, "text": raw_text, "portrait": portrait}
            self.dialog_blocks[self._dialog_edit_row] = blk
            self._refresh_dialog_list()
            self.listDialog.setCurrentRow(self._dialog_edit_row)
            self._persist_dialog_all()
            self.btnAddDialog.setText("Add to Queue (Ctrl+Enter)")
            self._clear_dialog_editor_fields()
            self._dialog_edit_row = None
            self.listDialog.clearSelection()
            self._update_dialog_hud()
            return

        paragraphs = [p.strip() for p in raw_text.split("\n\n") if p.strip()]
        for para in paragraphs:
            self.dialog_blocks.append({"speaker": speaker, "text": para, "portrait": portrait})
            if self.dialog_index < 0: self.dialog_index = 0

        self._refresh_dialog_list()
        if self.dialog_blocks:
            self.listDialog.setCurrentRow(len(self.dialog_blocks) - 1)

        self._persist_dialog_all()
        self.btnAddDialog.setText("Add to Queue (Ctrl+Enter)")
        self._clear_dialog_editor_fields()
        self.listDialog.clearSelection()
        self._update_dialog_hud()

    def _remove_selected_dialog(self):
        row = self.listDialog.currentRow()
        if row < 0: return
        del self.dialog_blocks[row]
        self.dialog_index = -1 if not self.dialog_blocks else min(self.dialog_index, len(self.dialog_blocks)-1)
        self._refresh_dialog_list(); self._persist_dialog_all(); self._update_dialog_hud()

    def _clear_dialog(self):
        if not self.dialog_blocks: return
        self.dialog_blocks.clear(); self.dialog_index = -1
        self._refresh_dialog_list(); self._persist_dialog_all(); self._update_dialog_hud()

    def _refresh_dialog_list(self):
        self.listDialog.clear()
        for i, b in enumerate(self.dialog_blocks, start=1):
            label = f"{i}. {(b.get('speaker') or 'Narrator')}: {b.get('text','')[:50]}"
            item = QtWidgets.QListWidgetItem(label, self.listDialog)
            # Bold the live/current block
            if (i - 1) == self.dialog_index:
                f = item.font(); f.setBold(True); item.setFont(f)
        self._highlight_dialog_current(); self._update_dialog_hud()

    def _highlight_dialog_current(self):
        if 0 <= self.dialog_index < self.listDialog.count():
            self.listDialog.setCurrentRow(self.dialog_index)

    def _update_dialog_hud(self):
        total = len(self.dialog_blocks)
        idx = (self.dialog_index + 1) if self.dialog_index >= 0 else 0
        sp  = self.dialog_blocks[self.dialog_index].get("speaker") if 0 <= self.dialog_index < total else "—"
        self.lblDialogHud.setText(f"{idx} / {total} — Speaker: {sp or 'Narrator'}")

    # ---------- Encounters tab ----------
    def _build_encounters_tab(self, tabs: QtWidgets.QTabWidget):
        page = QtWidgets.QWidget()
        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal, page)

        left = QtWidgets.QWidget(); lv = QtWidgets.QVBoxLayout(left); lv.setContentsMargins(8,8,8,8)
        self.listEncCombat = QtWidgets.QListWidget()
        self.listEncDialog = QtWidgets.QListWidget()
        lv.addWidget(QtWidgets.QLabel("Saved Combat Encounters")); lv.addWidget(self.listEncCombat, 1)
        lv.addWidget(QtWidgets.QLabel("Saved Dialog Encounters")); lv.addWidget(self.listEncDialog, 1)

        right = QtWidgets.QWidget(); rv = QtWidgets.QVBoxLayout(right); rv.setContentsMargins(8,8,8,8)
        self.btnSaveCombat = QtWidgets.QPushButton("Save Current Combat…")
        self.btnSaveDialog = QtWidgets.QPushButton("Save Current Dialog…")
        self.btnSendCombat = QtWidgets.QPushButton("Send Selected Combat ▶")
        self.btnSendDialog = QtWidgets.QPushButton("Send Selected Dialog 💬")
        rv.addWidget(self.btnSaveCombat); rv.addWidget(self.btnSaveDialog)
        rv.addStretch(1); rv.addWidget(self.btnSendCombat); rv.addWidget(self.btnSendDialog)

        split.addWidget(left); split.addWidget(right)
        split.setStretchFactor(0,1); split.setStretchFactor(1,1)

        lay = QtWidgets.QVBoxLayout(page); lay.setContentsMargins(0,0,0,0); lay.addWidget(split)
        tabs.addTab(page, "Encounters")

        self.btnSaveCombat.clicked.connect(self._save_current_combat)
        self.btnSaveDialog.clicked.connect(self._save_current_dialog)
        self.btnSendCombat.clicked.connect(self._send_selected_combat)
        self.btnSendDialog.clicked.connect(self._send_selected_dialog)

        self._refresh_encounters_lists()

    def _refresh_encounters_lists(self):
        self._enc_combat_cache = []; self._enc_dialog_cache = []
        self.listEncCombat.clear()
        for f in sorted(COMBAT_DIR.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                self._enc_combat_cache.append(data)
                QtWidgets.QListWidgetItem(f"{data.get('name','(unnamed)')}  [{f.stem}]", self.listEncCombat)
            except Exception: pass
        self.listEncDialog.clear()
        for f in sorted(DIALOG_DIR.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                self._enc_dialog_cache.append(data)
                QtWidgets.QListWidgetItem(f"{data.get('name','(unnamed)')}  [{f.stem}]", self.listEncDialog)
            except Exception: pass

    def _prompt_id_name(self, title: str):
        dlg = QtWidgets.QDialog(self); dlg.setWindowTitle(title)
        f = QtWidgets.QFormLayout(dlg)
        edId = QtWidgets.QLineEdit(); edName = QtWidgets.QLineEdit()
        f.addRow("ID (filename)", edId); f.addRow("Name", edName)
        box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        f.addRow(box); box.accepted.connect(dlg.accept); box.rejected.connect(dlg.reject)
        if dlg.exec() != QtWidgets.QDialog.Accepted: return None, None
        return edId.text().strip(), (edName.text().strip() or edId.text().strip())

    def _save_current_combat(self):
        if not self.combatants: self._toast("No combatants."); return
        enc_id, enc_name = self._prompt_id_name("Save Combat Encounter")
        if not enc_id: return
        counts = {"allies": {}, "opponents": {}}
        for m in self.combatants:
            side = "opponents" if m.get("isEnemy", False) else "allies"
            base = m.get("name","unknown").split(" ")[0]
            sid  = _slug(base)
            counts[side][sid] = counts[side].get(sid, 0) + 1
        data = {"encounter_id": enc_id, "name": enc_name, "type": "combat",
                "sides": {
                    "allies":    [{"source_id": s, "count": n} for s,n in counts["allies"].items()],
                    "opponents": [{"source_id": s, "count": n} for s,n in counts["opponents"].items()],
                },
                "created_at": _now_iso()}
        (COMBAT_DIR/f"{_slug(enc_id)}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        self._refresh_encounters_lists(); self._toast("Combat saved.")
        self._log(f"Saved combat: {enc_name} [{enc_id}]")

    def _save_current_dialog(self):
        if not self.dialog_blocks: self._toast("No dialog."); return
        enc_id, enc_name = self._prompt_id_name("Save Dialog Encounter")
        if not enc_id: return
        data = {"encounter_id": enc_id, "name": enc_name, "type": "dialog",
                "sequence": self.dialog_blocks, "created_at": _now_iso()}
        (DIALOG_DIR/f"{_slug(enc_id)}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        self._refresh_encounters_lists(); self._toast("Dialog saved.")
        self._log(f"Saved dialog: {enc_name} [{enc_id}]")

    def _send_selected_combat(self):
        row = self.listEncCombat.currentRow()
        if row < 0: return
        enc = self._enc_combat_cache[row]
        to_add = []
        for side_key, is_enemy in (("allies", False), ("opponents", True)):
            for e in enc.get("sides", {}).get(side_key, []):
                base = e.get("source_id","unknown"); count = int(e.get("count",1))
                used = _collect_suffixes(base, [c["name"] for c in self.combatants]+[x["name"] for x in to_add])
                for _ in range(max(1, count)):
                    suf = _next_suffix(used); used.add(suf)
                    name_exists = any(n.startswith(base+" ") or n==base for n in [c["name"] for c in self.combatants])
                    name = base if (count==1 and not name_exists) else f"{base} {suf}"
                    to_add.append({"name": name, "isEnemy": is_enemy, "maxHP": 10, "currentHP": 10, "icon": "", "statusEffects": [], "initiative": 0})
        self.combatants.extend(to_add)
        if self.turn_index < 0 and self.combatants: self.turn_index = 0
        self._refresh_combat_list(); self._persist_party()
        self._toast(f"Sent '{enc.get('name')}' to Combat.")
        self._log(f"Sent combat: {enc.get('name','(unnamed)')}")

    def _send_selected_dialog(self):
        row = self.listEncDialog.currentRow()
        if row < 0: return
        enc = self._enc_dialog_cache[row]
        self.dialog_blocks = enc.get("sequence", [])
        self.dialog_index = 0 if self.dialog_blocks else -1
        self._refresh_dialog_list(); self._persist_dialog_all()
        self._toast(f"Sent '{enc.get('name')}' to Dialog.")
        self._log(f"Sent dialog: {enc.get('name','(unnamed)')}")

    # ---------- Log tab ----------
    def _build_log_tab(self, tabs: QtWidgets.QTabWidget):
        page = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(page); v.setContentsMargins(8,8,8,8)
        self.listLog = QtWidgets.QListWidget()
        v.addWidget(self.listLog, 1)

        if LOG_FILE.exists():
            try:
                for line in LOG_FILE.read_text(encoding="utf-8").splitlines()[-300:]:
                    self.listLog.addItem(line)
                self.listLog.scrollToBottom()
            except Exception:
                pass

        tabs.addTab(page, "Log")

    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        if hasattr(self, "listLog") and self.listLog is not None:
            self.listLog.addItem(line)
            if self.listLog.count() > 500:
                self.listLog.takeItem(0)
            self.listLog.scrollToBottom()
        try:
            with LOG_FILE.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    # ---------- Settings tab ----------
    def _build_settings_tab(self, tabs: QtWidgets.QTabWidget):
        page = QtWidgets.QWidget()
        f = QtWidgets.QFormLayout(page); f.setContentsMargins(12,12,12,12)

        self.cmbThemeSettings = QtWidgets.QComboBox()
        names=[]
        try:
            if THEMES_DIR.exists():
                for p in sorted(THEMES_DIR.iterdir()):
                    if p.is_dir() and (p/"theme.json").exists(): names.append(p.name)
        except Exception:
            pass
        if not names:
            names = [self.theme_name] if self.theme_name else ["gm-modern"]
        self.cmbThemeSettings.addItems(names)
        self.cmbThemeSettings.setCurrentText(self.theme_name)
        self.cmbThemeSettings.currentTextChanged.connect(self._set_theme_from_settings)
        f.addRow("Overlay Theme", self.cmbThemeSettings)

        self.chkAutoRefresh = QtWidgets.QCheckBox("Enable")
        self.chkAutoRefresh.setChecked(self.auto_refresh)
        self.chkAutoRefresh.toggled.connect(self._set_auto_refresh)
        f.addRow("Auto Refresh", self.chkAutoRefresh)

        row = QtWidgets.QHBoxLayout()
        self.spnInterval = QtWidgets.QSpinBox(); self.spnInterval.setRange(100, 60000); self.spnInterval.setSingleStep(100)
        self.spnInterval.setValue(int(self.poll_ms))
        btnApply = QtWidgets.QPushButton("Apply")
        row.addWidget(self.spnInterval, 1); row.addWidget(btnApply)
        btnApply.clicked.connect(self._apply_interval_from_settings)
        f.addRow("Refresh (ms)", row)

        tabs.addTab(page, "Settings")

    def _set_theme_from_settings(self, name: str):
        if not name: return
        if hasattr(self, "cmbTheme"):
            old = self.cmbTheme.blockSignals(True)
            self.cmbTheme.setCurrentText(name)
            self.cmbTheme.blockSignals(old)
        self._set_theme_from_combo(name)

    def _apply_interval_from_settings(self):
        self.poll_ms = int(self.spnInterval.value())
        self._persist_config()
        self._toast(f"Refresh interval set to {self.poll_ms} ms.")

    # ---------- Notes (Markdown vault) ----------
    def _build_notes_tab(self, tabs: QtWidgets.QTabWidget):
        page = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(page); v.setContentsMargins(8,8,8,8); v.setSpacing(8)

        top = QtWidgets.QHBoxLayout()
        self.selNotes = QtWidgets.QComboBox(); self.selNotes.setMinimumWidth(220)
        self.btnNoteNew    = QtWidgets.QPushButton("New")
        self.btnNoteRename = QtWidgets.QPushButton("Rename")
        self.btnNoteDelete = QtWidgets.QPushButton("Delete")
        self.btnNoteOpen   = QtWidgets.QPushButton("Open")
        top.addWidget(QtWidgets.QLabel("File:"))
        top.addWidget(self.selNotes, 1)
        top.addWidget(self.btnNoteNew)
        top.addWidget(self.btnNoteRename)
        top.addWidget(self.btnNoteDelete)
        top.addWidget(self.btnNoteOpen)
        v.addLayout(top)

        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.edNotes = QtWidgets.QPlainTextEdit()
        self.edNotes.setPlaceholderText("# Session notes…\n\n- Use **Markdown** here\n- Autosaves to data/notes/")
        self.edNotes.textChanged.connect(self._notes_changed)

        self.prevNotes = QtWidgets.QTextEdit()
        self.prevNotes.setReadOnly(True)
        self.prevNotes.setAcceptRichText(True)

        split.addWidget(self.edNotes)
        split.addWidget(self.prevNotes)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        v.addWidget(split, 1)

        tabs.addTab(page, "Notes")

        self._notes_timer = QtCore.QTimer(self)
        self._notes_timer.setSingleShot(True)
        self._notes_timer.setInterval(600)

        self.selNotes.currentTextChanged.connect(self._notes_file_selected)
        self.btnNoteNew.clicked.connect(self._notes_new_file)
        self.btnNoteRename.clicked.connect(self._notes_rename_file)
        self.btnNoteDelete.clicked.connect(self._notes_delete_file)
        self.btnNoteOpen.clicked.connect(
            lambda: QtGui.QDesktopServices.openUrl(
                QtCore.QUrl.fromLocalFile(str(self._notes_current_path))
            )
        )

        self._notes_refresh_list()
        if not DEFAULT_NOTE.exists():
            DEFAULT_NOTE.write_text("# Notes\n\n", encoding="utf-8")
        self._notes_open_file(DEFAULT_NOTE)

    def _notes_refresh_list(self):
        names = [p.name for p in sorted(VAULT_DIR.glob("*.md"))]
        cur = getattr(self, "_notes_current_path", DEFAULT_NOTE)
        cur_name = cur.name if cur else ""
        self.selNotes.blockSignals(True)
        self.selNotes.clear()
        if not names:
            names = [DEFAULT_NOTE.name]
        self.selNotes.addItems(names)
        idx = self.selNotes.findText(cur_name)
        if idx < 0:
            idx = self.selNotes.findText(DEFAULT_NOTE.name)
        if idx >= 0:
            self.selNotes.setCurrentIndex(idx)
        self.selNotes.blockSignals(False)

    def _notes_file_selected(self, name: str):
        if not name:
            return
        path = VAULT_DIR / name
        if not path.suffix:
            path = path.with_suffix(".md")
        if not path.exists():
            try:
                path.write_text("", encoding="utf-8")
            except Exception:
                return
        self._notes_open_file(path)

    def _notes_open_file(self, path: Path):
        self._notes_current_path = Path(path)
        try:
            txt = self._notes_current_path.read_text(encoding="utf-8")
        except Exception:
            txt = ""
        self.edNotes.blockSignals(True)
        self.edNotes.setPlainText(txt)
        self.edNotes.blockSignals(False)
        self._notes_render_preview(txt)
        self._notes_refresh_list()
        idx = self.selNotes.findText(self._notes_current_path.name)
        if idx >= 0:
            self.selNotes.setCurrentIndex(idx)

    def _notes_changed(self):
        self._notes_timer.stop()
        # Avoid multiple connections stacking
        try:
            self._notes_timer.timeout.disconnect()
        except Exception:
            pass
        self._notes_timer.timeout.connect(self._notes_save_and_preview)
        self._notes_timer.start()

    def _notes_save_and_preview(self):
        txt = self.edNotes.toPlainText()
        try:
            self._notes_current_path.parent.mkdir(parents=True, exist_ok=True)
            self._notes_current_path.write_text(txt, encoding="utf-8")
        except Exception:
            pass
        self._notes_render_preview(txt)

    def _notes_render_preview(self, txt: str):
        try:
            self.prevNotes.setMarkdown(txt)
        except Exception:
            self.prevNotes.setPlainText(txt)

    def _notes_new_file(self):
        name, ok = QtWidgets.QInputDialog.getText(self, "New Note", "Filename (without extension):")
        if not ok or not name.strip():
            return
        fn = _slug(name.strip()) or "untitled"
        path = VAULT_DIR / f"{fn}.md"
        if path.exists():
            QtWidgets.QMessageBox.information(self, "Exists", f"'{path.name}' already exists.")
            return
        try:
            path.write_text("# New Note\n\n", encoding="utf-8")
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Error", f"Could not create file:\n{e}")
            return
        self._notes_open_file(path)

    def _notes_rename_file(self):
        cur = getattr(self, "_notes_current_path", DEFAULT_NOTE)
        if not cur or not cur.exists():
            return
        name, ok = QtWidgets.QInputDialog.getText(self, "Rename Note", "New filename (without extension):", text=cur.stem)
        if not ok or not name.strip():
            return
        fn = _slug(name.strip()) or "untitled"
        new_path = cur.with_name(f"{fn}.md")
        if new_path.exists() and new_path != cur:
            QtWidgets.QMessageBox.information(self, "Exists", f"'{new_path.name}' already exists.")
            return
        try:
            cur.rename(new_path)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Error", f"Could not rename:\n{e}")
            return
        self._notes_open_file(new_path)

    def _notes_delete_file(self):
        cur = getattr(self, "_notes_current_path", DEFAULT_NOTE)
        if not cur or not cur.exists():
            return
        if cur == DEFAULT_NOTE:
            QtWidgets.QMessageBox.information(self, "Protected", "The default notes.md cannot be deleted.")
            return
        ret = QtWidgets.QMessageBox.question(self, "Delete Note", f"Delete '{cur.name}'?", QtWidgets.QMessageBox.Yes|QtWidgets.QMessageBox.No)
        if ret != QtWidgets.QMessageBox.Yes:
            return
        try:
            cur.unlink(missing_ok=True)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Error", f"Could not delete:\n{e}")
            return
        self._notes_open_file(DEFAULT_NOTE)

    # ---------- global actions ----------
    def _advance(self):
        if self.mode == "combat": self._advance_combat_next()
        else: self._dialog_next_local()

    def _prev(self):
        if self.mode == "combat": self._advance_combat_prev()
        else: self._dialog_prev_local()

    def _toggle_mode(self):
        if hasattr(self, "btnMode") and isinstance(self.btnMode, QtWidgets.QToolButton):
            self.btnMode.setChecked(not self.btnMode.isChecked())
            return
        self.mode = "dialog" if self.mode == "combat" else "combat"
        self._update_mode_button_text()
        self._persist_config()
        self._toast(f"Mode → {self.mode.capitalize()}")

    def _load_status_catalog(self) -> List[str]:
        names=[]
        try:
            if STATUS_DIR.exists():
                for fn in os.listdir(STATUS_DIR):
                    if fn.lower().endswith(".png"):
                        names.append(os.path.splitext(fn)[0])
        except Exception: pass
        if not names:
            names = ["Poisoned","Stunned","Prone","Blessed","Charmed","Grappled","Frightened","Invisible"]
        return sorted(dict.fromkeys(names), key=str.lower)

    # ---------- persistence ----------
    def _persist_all(self):
        self._persist_party(); self._persist_dialog_all(); self._persist_config()

    def _persist_party(self):
        write_json(PARTY_FP, {"party": self.combatants})

    def _persist_config(self):
        cfg = safe_json(CONFIG_FP, {})
        cfg["combat_mode"] = (self.mode == "combat")
        cfg["turnIndex"]   = max(0, self.turn_index) if self.combatants else 0
        cfg["dialogIndex"] = max(0, self.dialog_index) if self.dialog_blocks else 0
        cfg["theme"] = self.theme_name
        cfg["auto_refresh"] = bool(self.auto_refresh)
        cfg["poll_ms"] = int(max(100, self.poll_ms))
        cfg["ui_dark"] = bool(self.ui_dark)
        write_json(CONFIG_FP, cfg)

    def _persist_dialog_all(self):
        blocks_text = []
        for b in self.dialog_blocks:
            sp = (b.get("speaker") or "").strip()
            tx = (b.get("text") or "").strip()
            blocks_text.append(f"{sp}: {tx}" if sp and tx else (sp or tx))
        write_dialog_txt(blocks_text)
        meta = {}
        for i, b in enumerate(self.dialog_blocks):
            meta[str(i)] = {"portrait": b.get("portrait","")}
        write_json(DIALOGMETA, meta)

    # ---------- misc ----------
    def _toast(self, msg: str):
        QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), msg, self, self.rect(), 1500)

    def _center_on_screen(self, widget: QtWidgets.QWidget):
        QtWidgets.QApplication.processEvents()
        screen = QtWidgets.QApplication.primaryScreen()
        if not screen: return
        ag = screen.availableGeometry(); r = widget.frameGeometry()
        w = min(r.width() or 800, ag.width()); h = min(r.height() or 450, ag.height())
        x = ag.left() + (ag.width()-w)//2; y = ag.top() + (ag.height()-h)//2
        widget.setGeometry(x,y,w,h); widget.raise_(); widget.activateWindow()

    def _focus_active_search(self):
        if self.grpCombat.isChecked() or True:  # always available
            self.searchCombat.setFocus(); self.searchCombat.selectAll()

# ---------- helpers ----------
def _collect_suffixes(base_name: str, names: List[str]) -> set:
    base = base_name.strip(); out = set()
    for n in names:
        if n == base: out.add("")
        if n.startswith(base + " "):
            tail = n[len(base)+1:].strip()
            if tail: out.add(tail)
    return out

def _next_suffix(not_in: set) -> str:
    for i in range(26):
        s = chr(65+i)
        if s not in not_in: return s
    k = 1
    while True:
        s = f"A{k}"
        if s not in not_in: return s
        k += 1

class _CombatantEditor(QtWidgets.QDialog):
    def __init__(self, parent=None, data: Optional[Dict] = None):
        super().__init__(parent)
        self.setWindowTitle("Combatant")
        f = QtWidgets.QFormLayout(self)
        self.edName = QtWidgets.QLineEdit((data or {}).get("name",""))
        self.edHP  = QtWidgets.QSpinBox(); self.edHP.setRange(1, 999); self.edHP.setValue(int((data or {}).get("maxHP", 10)))
        self.cbSide= QtWidgets.QComboBox(); self.cbSide.addItems(["allies","opponents"])
        if (data or {}).get("isEnemy") is not None:
            self.cbSide.setCurrentText("opponents" if (data or {}).get("isEnemy") else "allies")
        self.edPortrait = QtWidgets.QLineEdit((data or {}).get("icon",""))
        self.edInit = QtWidgets.QSpinBox(); self.edInit.setRange(-50,50); self.edInit.setValue(int((data or {}).get("initiative",0)))
        btnBrowse = QtWidgets.QPushButton("Browse…"); btnBrowse.clicked.connect(self._browse)
        rowp = QtWidgets.QHBoxLayout(); rowp.addWidget(self.edPortrait,1); rowp.addWidget(btnBrowse)
        f.addRow("Name", self.edName)
        f.addRow("HP (max)", self.edHP)
        f.addRow("Side", self.cbSide)
        f.addRow("Portrait PNG", rowp)
        f.addRow("Initiative (roll)", self.edInit)
        box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok|QtWidgets.QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept); box.rejected.connect(self.reject)
        f.addRow(box)

    def _browse(self):
        p, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Portrait", "", "Images (*.png *.jpg *.jpeg *.webp)")
        if p:
            try: self.edPortrait.setText(str(Path(p).resolve()).replace(str(APP_DIR)+os.sep, ""))
            except Exception: self.edPortrait.setText(p)

    def payload(self) -> Dict:
        hpmax = int(self.edHP.value())
        return {
            "name": self.edName.text().strip() or "Unnamed",
            "hpmax": hpmax,
            "side": self.cbSide.currentText(),
            "portrait": self.edPortrait.text().strip(),
            "initiative": int(self.edInit.value()),
        }
