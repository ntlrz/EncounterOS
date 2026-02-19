from __future__ import annotations
import json
import os
import importlib
from typing import List, Dict, Optional, Tuple
from pathlib import Path
from PySide6 import QtWidgets, QtGui, QtCore

# Import refactored modules
from app_paths import (
    APP_DIR, PARTY_FP, CONFIG_FP, THEMES_DIR, DATA_ROOT,
    VAULT_DIR, DIALOG_FP, DIALOG_DIR, DIALOGMETA,
    LOG_FILE, ROSTERS_DIR, BACKUPS_DIR,
)
from helpers import (
    safe_json, write_json, now_iso, slug,
    parse_rank, rank_label_for_pack, roll_d20,
    load_status_catalog, collect_suffixes, next_suffix,
    export_backup, restore_backup,
)
from styles import DARK_QSS, LIGHT_QSS, MD_CSS
from combat_tab import CombatTab
from dialog_tab import DialogTab
from notes_tab import NotesTab
from encounters_tab import EncountersTab
from rosters_tab import RostersTab
from timers_tab import TimersTab  # top-level import

class GMWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EncounterOS — GM")
        self.resize(1220, 840)

        cfg0 = safe_json(CONFIG_FP, {})
        self.theme_name   = cfg0.get("theme", "gm_modern")
        self.auto_refresh = bool(cfg0.get("auto_refresh", True))
        self.poll_ms      = max(100, int(cfg0.get("poll_ms", 200)))
        self.ui_dark      = bool(cfg0.get("ui_dark", True))
        
        ov = cfg0.get("overlay") or {}
        self.ov_screen = ov.get("screen")
        self.ov_fit    = (ov.get("fit") or "contain")
        self.ov_full   = bool(ov.get("fullscreen", True))

        self.mode = str(cfg0.get("mode", "combat") or "combat")
        self.overlay_on = False

        self._status_catalog = load_status_catalog()

        # Build UI from new modules
        self._build_menubar()
        self._build_toolbar()

        # Left pane: Combat & Dialog in a vertical splitter
        self.combat_tab = CombatTab(self)
        self.dialog_tab = DialogTab(self)
        left_splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        left_splitter.addWidget(self.combat_tab)
        left_splitter.addWidget(self.dialog_tab)
        left_splitter.setStretchFactor(0, 7)
        left_splitter.setStretchFactor(1, 3)

        # Right pane: Notes, Encounters, and Rosters in a tab widget
        self.tabs = QtWidgets.QTabWidget()
        self.notes_tab = NotesTab(self)
        self.encounters_tab = EncountersTab(self)
        self.rosters_tab = RostersTab(self)
        self.timers_tab = TimersTab(self)
        self.tabs.addTab(self.rosters_tab, "Rosters")
        self.tabs.addTab(self.encounters_tab, "Saved Encounters")
        self.tabs.addTab(self.notes_tab, "Notes")
        self.tabs.addTab(self.timers_tab, "Timers")

        # Main splitter: Left pane vs. Right pane
        main_splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        main_splitter.addWidget(left_splitter)
        main_splitter.addWidget(self.tabs)
        main_splitter.setStretchFactor(0, 7)
        main_splitter.setStretchFactor(1, 3)

        self.setCentralWidget(main_splitter)
        self._apply_ui_theme(self.ui_dark)

        # Shortcuts
        QtGui.QShortcut(QtGui.QKeySequence("F4"), self, activated=self._toggle_overlay_hotkey)
        QtGui.QShortcut(QtGui.QKeySequence("F5"), self, activated=self._advance_mode)
        QtGui.QShortcut(QtGui.QKeySequence("F7"), self, activated=self._prev_mode)
        QtGui.QShortcut(QtGui.QKeySequence("F6"), self, activated=self._toggle_mode)
        QtGui.QShortcut(QtGui.QKeySequence("/"),  self, activated=self._focus_active_search)
        QtGui.QShortcut(QtGui.QKeySequence("Ctrl+Return"), self, activated=self._add_dialog_block)
        QtGui.QShortcut(QtGui.QKeySequence("F8"), self, activated=self._dialog_make_current)

        # Overlay link
        self.overlay_win: Optional[QtWidgets.QWidget] = None
        try:
            mod = importlib.import_module("tracker_overlay")
            self._OverlayClass = getattr(mod, "Overlay", None)
        except Exception as e:
            print("[gm_ui] tracker_overlay import problem:", e)
            self._OverlayClass = None

        # initial sync
        self._sync_toolbar()
        self._persist_all()
        
        # allow tabs to create the dialog without import cycles
        self._StatusEditorDialog = StatusEditorDialog

    def _persist_all(self):
        self.combat_tab._persist_party()
        self.dialog_tab._persist_dialog()

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
        actExportBackup = mFile.addAction("Export Backup…")
        actExportBackup.triggered.connect(self._export_backup)
        actRestoreBackup = mFile.addAction("Restore Backup…")
        actRestoreBackup.triggered.connect(self._restore_backup)
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
        actReload = mOverlay.addAction("Reload Now"); actReload.triggered.connect(self._reload_now)
        self.actAutoRefresh = mOverlay.addAction("Auto Refresh")
        self.actAutoRefresh.setCheckable(True)
        self.actAutoRefresh.setChecked(self.auto_refresh)
        self.actAutoRefresh.toggled.connect(self._set_auto_refresh)
        actInterval = mOverlay.addAction("Set Refresh Interval…")
        actInterval.triggered.connect(self._set_poll_interval)
        self._themes_menu = mOverlay.addMenu("Theme")
        self._populate_themes_menu()
        
        # --- Screen submenu (radio)
        mScreens = mOverlay.addMenu("Target Screen")
        grp = QtGui.QActionGroup(self); grp.setExclusive(True)
        actPrim = mScreens.addAction("(Primary)"); actPrim.setCheckable(True)
        actPrim.setChecked(self.ov_screen is None)
        actPrim.triggered.connect(lambda: self._ov_set_screen(None))
        grp.addAction(actPrim)
        for s in QtGui.QGuiApplication.screens():
            a = mScreens.addAction(s.name()); a.setCheckable(True)
            a.setChecked(self.ov_screen == s.name())
            a.triggered.connect(lambda chk, name=s.name(): self._ov_set_screen(name))
            grp.addAction(a)

        # --- Fit mode (radio)
        mFit = mOverlay.addMenu("Fit Mode")
        grpFit = QtGui.QActionGroup(self); grpFit.setExclusive(True)
        for mode in ("contain","cover","stretch"):
            a = mFit.addAction(mode); a.setCheckable(True)
            a.setChecked(self.ov_fit == mode)
            a.triggered.connect(lambda chk, mname=mode: self._ov_set_fit(mname))
            grpFit.addAction(a)

        # --- Fullscreen toggle
        actFS = mOverlay.addAction("Fullscreen")
        actFS.setCheckable(True); actFS.setChecked(self.ov_full)
        actFS.toggled.connect(self._ov_toggle_fullscreen)

        # Optional quick action: snap now
        mOverlay.addSeparator()
        actSnap = mOverlay.addAction("Snap Overlay to Selected Screen")
        actSnap.triggered.connect(self._ov_apply_screen_now)

    def _build_toolbar(self):
        tb = self.addToolBar("Main")
        tb.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        
        # Overlay control
        self.btnOverlay = QtWidgets.QToolButton()
        self.btnOverlay.setText("Overlay OFF")
        self.btnOverlay.setCheckable(True)
        self.btnOverlay.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_ComputerIcon))
        self.btnOverlay.toggled.connect(self._set_overlay)
        tb.addWidget(self.btnOverlay)

        # Mode button
        self.btnMode = QtWidgets.QToolButton()
        self.btnMode.setCheckable(True)
        self.btnMode.setChecked(True)
        self.btnMode.toggled.connect(self._mode_button_toggled)
        self._update_mode_button_text()
        tb.addWidget(self.btnMode)

        # Theme combo box with preview delegate
        self.cmbTheme = QtWidgets.QComboBox()
        self.cmbTheme.setMinimumWidth(220)
        self.cmbTheme.setItemDelegate(ThemePreviewDelegate(self.cmbTheme, THEMES_DIR))
        self._populate_themes_combo()
        if self.theme_name in [self.cmbTheme.itemText(i) for i in range(self.cmbTheme.count())]:
            self.cmbTheme.setCurrentText(self.theme_name)
        self.cmbTheme.currentTextChanged.connect(self._set_theme_from_combo)
        tb.addWidget(self.cmbTheme)

    def _advance_mode(self):
        if self.mode == "combat":
            self.combat_tab._advance_combat_next()
        elif self.mode == "dialog":
            self.dialog_tab._dialog_next_local()

    def _prev_mode(self):
        if self.mode == "combat":
            self.combat_tab._advance_combat_prev()
        elif self.mode == "dialog":
            self.dialog_tab._dialog_prev_local()

    def _toggle_mode(self):
        self.btnMode.setChecked(not self.btnMode.isChecked())

    def _focus_active_search(self):
        if self.mode == "combat":
            self.combat_tab.searchCombat.setFocus()
        elif self.mode == "dialog":
            self.dialog_tab.searchDialog.setFocus()

    def _add_dialog_block(self):
        if self.mode == "dialog":
            self.dialog_tab._add_dialog_block()

    def _dialog_make_current(self):
        if self.mode == "dialog":
            self.dialog_tab._dialog_make_current()

    def _persist_config(self):
        cfg = {
            "theme": self.theme_name,
            "auto_refresh": self.auto_refresh,
            "poll_ms": self.poll_ms,
            "ui_dark": self.ui_dark,
            "mode": self.mode,  # "combat" or "dialog" - controls overlay display
            "overlay": {
                "screen": self.ov_screen,
                "fit": self.ov_fit,
                "fullscreen": self.ov_full,
            },
        }
        write_json(CONFIG_FP, cfg)

    def _toast(self, message: str):
        self.statusBar().showMessage(message, 3000)

    def _populate_themes_combo(self):
        self.cmbTheme.clear()
        names=[]
        try:
            if THEMES_DIR.exists():
                for p in sorted(THEMES_DIR.iterdir()):
                    if p.is_dir() and (p/"theme.json").exists(): names.append(p.name)
        except Exception:
            pass
        if not names:
            names = [self.theme_name] if self.theme_name else ["gm_modern"]
        self.cmbTheme.addItems(names)

    def _populate_themes_menu(self):
        self._themes_menu.clear()
        names=[]
        try:
            if THEMES_DIR.exists():
                for p in sorted(THEMES_DIR.iterdir()):
                    if p.is_dir() and (p/"theme.json").exists(): names.append(p.name)
        except Exception:
            pass
        if not names:
            names = [self.theme_name] if self.theme_name else ["gm_modern"]
        group = QtGui.QActionGroup(self)
        group.setExclusive(True)
        for n in names:
            act = self._themes_menu.addAction(n)
            act.setCheckable(True)
            act.setChecked(n == self.theme_name)
            act.triggered.connect(lambda checked, s=n: self.cmbTheme.setCurrentText(s))
            group.addAction(act)

    def _set_theme_from_combo(self, name: str):
        if not name:
            return
        self.theme_name = name.strip()
        self._persist_config()
        # immediately push theme change to overlay if running
        if self.overlay_win:
            self.overlay_win.theme_name = self.theme_name
            self.overlay_win.theme = self.overlay_win._load_theme()
            self.overlay_win.repaint()
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
        # Immediately push mode change to overlay if running
        if self.overlay_win:
            self.overlay_win.mode = self.mode
            self.overlay_win.repaint()

    def _set_overlay(self, on: bool):
        self.overlay_on = on
        self.btnOverlay.setText("Overlay ON" if on else "Overlay OFF")
        if on and hasattr(self, "_OverlayClass") and self._OverlayClass:
            if not self.overlay_win:
                self.overlay_win = self._OverlayClass()
                self.overlay_win.set_fit_mode(self.ov_fit)
            self.overlay_win.move_to_screen(self.ov_screen)
            if self.ov_full:
                self.overlay_win.showFullScreen()
            else:
                self.overlay_win.show()
        elif self.overlay_win:
            self.overlay_win.hide()

    def _toggle_overlay_hotkey(self):
        self.btnOverlay.setChecked(not self.btnOverlay.isChecked())

    def _reload_now(self):
        self._persist_config()
        self.combat_tab._persist_party()
        self.dialog_tab._persist_dialog()
        self._toast("Requested overlay reload.")

    def _set_auto_refresh(self, on: bool):
        self.auto_refresh = bool(on)
        self._persist_config()
        self._toast(f"Auto-refresh {'ON' if on else 'OFF'}.")

    def _set_poll_interval(self):
        ms, ok = QtWidgets.QInputDialog.getInt(self, "Refresh Interval", "Milliseconds (>=100):", int(self.poll_ms), 100, 60000, 100)
        if not ok:
            return
        self.poll_ms = int(ms)
        self._persist_config()
        self._toast(f"Refresh interval set to {self.poll_ms} ms.")

    def _toggle_ui_dark(self, on: bool):
        self.ui_dark = bool(on)
        self._apply_ui_theme(self.ui_dark)
        self._persist_config()

    def _apply_ui_theme(self, dark: bool):
        self.setStyleSheet(DARK_QSS if dark else LIGHT_QSS)

    def _sync_toolbar(self):
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

    def _ov_set_screen(self, name: str | None):
        self.ov_screen = name
        self._persist_config()
        if self.overlay_win:
            self.overlay_win.move_to_screen(name)

    def _ov_set_fit(self, mode: str):
        self.ov_fit = mode
        self._persist_config()
        if self.overlay_win:
            self.overlay_win.set_fit_mode(mode)

    def _ov_toggle_fullscreen(self, on: bool):
        self.ov_full = bool(on)
        self._persist_config()
        if self.overlay_win:
            if on:
                self.overlay_win.showFullScreen()
            else:
                self.overlay_win.showNormal()
            self.overlay_win.move_to_screen(self.ov_screen)

    def _ov_apply_screen_now(self):
        if self.overlay_win:
            self.overlay_win.move_to_screen(self.ov_screen)

    def _log(self, text: str):
        entry = f"[{now_iso()}] {text}"
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(entry + "\n")
        print(entry)

    def _export_backup(self):
        from datetime import datetime
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export Backup",
            str(BACKUPS_DIR / f"encounteros-backup-{stamp}.zip"),
            "ZIP (*.zip)"
        )
        if not path:
            return
        from pathlib import Path
        dest = Path(path)
        if dest.suffix.lower() != ".zip":
            dest = dest.with_suffix(".zip")
        try:
            export_backup(APP_DIR, dest, include_data=True)
            self._toast(f"Backup saved: {dest.name}")
            self._log(f"Exported backup to {dest}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Export Failed", str(e))

    def _restore_backup(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Restore Backup", str(BACKUPS_DIR), "ZIP (*.zip)"
        )
        if not path:
            return
        from pathlib import Path
        zip_path = Path(path)
        ok, msg = restore_backup(zip_path, APP_DIR, overwrite=False)
        if ok:
            self._toast("Backup restored. Restart the app to use restored data.")
            self._log(f"Restored backup from {zip_path}")
            QtWidgets.QMessageBox.information(
                self, "Restore Complete",
                "Backup restored. You may need to restart EncounterOS for all changes to take effect."
            )
            return
        if "already exists" in msg:
            reply = QtWidgets.QMessageBox.question(
                self, "Overwrite?",
                msg + "\n\nOverwrite existing files and restore from backup?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No
            )
            if reply == QtWidgets.QMessageBox.Yes:
                ok2, msg2 = restore_backup(zip_path, APP_DIR, overwrite=True)
                if ok2:
                    self._toast("Backup restored.")
                    self._log(f"Restored backup from {zip_path}")
                    QtWidgets.QMessageBox.information(self, "Restore Complete",
                        "Backup restored. Consider restarting the app.")
                else:
                    QtWidgets.QMessageBox.critical(self, "Restore Failed", msg2)
        else:
            QtWidgets.QMessageBox.critical(self, "Restore Failed", msg)

    def _on_combat_selection_changed(self):
        pass
    
    def _on_dialog_row_changed(self, new_row: int):
        if self.overlay_win:
            self.dialog_tab._persist_dialog_state()

    def _wrap_spin_with_nudgers(self, spinbox):
        h = QtWidgets.QHBoxLayout()
        h.setContentsMargins(0,0,0,0)
        btnM1 = QtWidgets.QToolButton(text="-1")
        btnM5 = QtWidgets.QToolButton(text="-5")
        btnP1 = QtWidgets.QToolButton(text="+1")
        btnP5 = QtWidgets.QToolButton(text="+5")
        btnM1.clicked.connect(lambda: spinbox.setValue(spinbox.value()-1))
        btnM5.clicked.connect(lambda: spinbox.setValue(spinbox.value()-5))
        btnP1.clicked.connect(lambda: spinbox.setValue(spinbox.value()+1))
        btnP5.clicked.connect(lambda: spinbox.setValue(spinbox.value()+5))
        h.addWidget(spinbox)
        h.addWidget(btnM5); h.addWidget(btnM1); h.addWidget(btnP1); h.addWidget(btnP5)
        w = QtWidgets.QWidget()
        w.setLayout(h)
        return w
        
    def closeEvent(self, a):
        # Check for unsaved notes before closing
        if hasattr(self, "notes_tab") and self.notes_tab.has_unsaved_changes():
            reply = QtWidgets.QMessageBox.question(
                self,
                "Unsaved Changes",
                "You have unsaved changes in your notes. Do you want to save before closing?",
                QtWidgets.QMessageBox.Save | QtWidgets.QMessageBox.Discard | QtWidgets.QMessageBox.Cancel,
                QtWidgets.QMessageBox.Save
            )
            if reply == QtWidgets.QMessageBox.Save:
                self.notes_tab._save_note()
            elif reply == QtWidgets.QMessageBox.Cancel:
                a.ignore()
                return
        
        if self.overlay_win:
            self.overlay_win.close()
        a.accept()


# Theme preview delegate: draw a small color swatch next to theme name in combo
class ThemePreviewDelegate(QtWidgets.QStyledItemDelegate):
    def __init__(self, parent=None, themes_dir=None):
        super().__init__(parent)
        self._themes_dir = themes_dir or THEMES_DIR

    def _theme_preview_color(self, theme_name: str) -> str:
        if not theme_name or not self._themes_dir:
            return "#333333"
        try:
            fp = self._themes_dir / theme_name / "theme.json"
            if not fp.exists():
                return "#333333"
            data = json.load(fp.open("r", encoding="utf-8"))
            colors = (data.get("vars") or {}).get("colors") or {}
            return colors.get("card_bg") or colors.get("dialog_bg") or colors.get("border_idle") or "#333333"
        except Exception:
            return "#333333"

    def paint(self, painter, option, index):
        theme_name = index.data(QtCore.Qt.DisplayRole) or ""
        color_hex = self._theme_preview_color(theme_name)
        r = option.rect
        swatch_w = 24
        padding = 4
        # Swatch rect
        swatch = QtCore.QRect(r.x() + padding, r.y() + (r.height() - swatch_w) // 2, swatch_w, swatch_w)
        painter.fillRect(swatch, QtGui.QColor(color_hex))
        painter.setPen(QtGui.QColor("#888888"))
        painter.drawRect(swatch)
        # Text
        text_rect = QtCore.QRect(swatch.right() + padding, r.y(), r.width() - swatch_w - padding * 3, r.height())
        painter.setPen(option.palette.color(QtGui.QPalette.Text))
        painter.drawText(text_rect, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, theme_name)


# Entity Dialog Class
class EntityDialog(QtWidgets.QDialog):
    def __init__(self, parent: GMWindow, data: Dict):
        super().__init__(parent)
        self.setWindowTitle(f"Edit Entity: {data.get('name', 'New')}")
        self.setMinimumWidth(300)
        self.data = data
        self.parent = parent
        
        f = QtWidgets.QFormLayout(self)
        self.edName = QtWidgets.QLineEdit(); self.edName.setText(data.get("name", "New Creature"))
        self.edHP = QtWidgets.QSpinBox(); self.edHP.setRange(0, 9999); self.edHP.setValue(int((data or {}).get("hpMax", 1)))
        self.cbSide = QtWidgets.QComboBox()
        self.cbSide.addItems(["Friendly", "Neutral", "Enemy"])
        self.cbSide.setCurrentIndex(["Friendly", "Neutral", "Enemy"].index(data.get("side", "Enemy")))
        self.edPortrait = QtWidgets.QLineEdit(); self.edPortrait.setText(data.get("portrait", ""))
        self.edInit = QtWidgets.QSpinBox(); self.edInit.setRange(-50, 50); self.edInit.setValue(int((data or {}).get("initMod", (data or {}).get("initiative", 0))))

        f.addRow("Name", self.edName)
        f.addRow("HP (max)", self.parent._wrap_spin_with_nudgers(self.edHP))
        f.addRow("Side", self.cbSide)
        rowp = QtWidgets.QHBoxLayout(); rowp.addWidget(self.edPortrait,1); 
        btnBrowse = QtWidgets.QPushButton("Browse…"); btnBrowse.clicked.connect(self._browse)
        rowp.addWidget(btnBrowse)
        f.addRow("Portrait PNG", rowp)
        f.addRow("Initiative (roll)", self.parent._wrap_spin_with_nudgers(self.edInit))
        
        box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok|QtWidgets.QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept); box.rejected.connect(self.reject)
        f.addRow(box)

    def _browse(self):
        p, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Portrait", "", "Images (*.png *.jpg *.jpeg *.webp)")
        if p:
            try:
                from app_paths import APP_DIR
                rel_path = str(Path(p).resolve()).replace(str(APP_DIR)+os.sep, "")
                self.edPortrait.setText(rel_path)
            except Exception:
                self.edPortrait.setText(p)

    def payload(self) -> Dict:
        hpmax = int(self.edHP.value())
        return {
            "name": self.edName.text().strip(),
            "hp": hpmax if (self.data or {}).get("hp") is None else (self.data or {}).get("hp"),
            "hpMax": hpmax,
            "initMod": int(self.edInit.value()),
            "initTotal": (self.data or {}).get("initTotal"),
            "initRoll": (self.data or {}).get("initRoll"),
            "notes": (self.data or {}).get("notes", ""),
            "statuses": (self.data or {}).get("statuses", []),
            "portrait": self.edPortrait.text().strip() or None,
            "side": self.cbSide.currentText(),
        }

# Status Editor Class
class StatusEditorDialog(QtWidgets.QDialog):
    def __init__(self, parent: GMWindow, current_statuses: list[str], catalog: list[str]):
        super().__init__(parent)
        self.setWindowTitle("Edit Statuses")
        self.setMinimumWidth(300)
        self.current_statuses = current_statuses
        self.catalog = catalog
        self.parent = parent
        self.cbs = {}

        v = QtWidgets.QVBoxLayout(self)
        self.list = QtWidgets.QListWidget()
        self.list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        v.addWidget(self.list)

        for s in sorted(self.catalog, key=str.lower):
            item = QtWidgets.QListWidgetItem(s)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked if s in current_statuses else QtCore.Qt.Unchecked)
            self.list.addItem(item)
            
        box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept); box.rejected.connect(self.reject)
        v.addWidget(box)

    def payload(self) -> list[str]:
        out = []
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.checkState() == QtCore.Qt.Checked:
                out.append(item.text())
        return out