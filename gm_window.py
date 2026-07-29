from __future__ import annotations
import json
import os
from typing import List, Dict, Optional, Tuple
from pathlib import Path
from uuid import uuid4
from PySide6 import QtWidgets, QtGui, QtCore

# Import refactored modules
from app_paths import (
    APP_DIR, PARTY_FP, CONFIG_FP, THEMES_DIR, DATA_ROOT,
    VAULT_DIR, DIALOG_FP, DIALOG_DIR, DIALOGMETA,
    LOG_FILE, ROSTERS_DIR, BACKUPS_DIR,
)
from helpers import (
    safe_json, load_json, write_json, now_iso, slug, config_bool, config_choice,
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
from dice_tab import DiceTab
from shortcuts_editor import ShortcutEditorDialog, get_shortcuts_from_config
from dock_layout import WINDOW_STATE_VERSION, encode_bytes, decode_bytes
from portrait_library import PortraitLibraryWidget
from combat_metrics import (
    coerce_metric_int,
    metric_values,
    resolve_combat_metric,
    resolve_secondary_combat_metric,
    secondary_metric_warning,
)
from tracker_overlay import Overlay, overlay_runtime_log

OVERLAY_THEME_LABELS = {
    "gm_modern": "GM Modern",
    "dark_parchment": "Dark Parchment",
    "rpg-retro": "RPG Retro",
}
ENEMY_HEALTH_DISCLOSURE_LABELS = {
    "hidden": "Hidden",
    "condition": "Condition Only",
    "full": "Full Values",
}


class GMWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EncounterOS — GM")
        self.resize(1220, 840)

        cfg_result = load_json(CONFIG_FP)
        self._config_write_blocked = False
        if cfg_result.valid and isinstance(cfg_result.data, dict):
            cfg0 = dict(cfg_result.data)
        elif cfg_result.missing:
            cfg0 = {}
        else:
            cfg0 = {}
            self._config_write_blocked = True
        self._config_document = dict(cfg0)
        self.theme_name   = cfg0.get("theme", "gm_modern")
        self.auto_refresh = bool(cfg0.get("auto_refresh", True))
        try:
            self.poll_ms = max(100, int(cfg0.get("poll_ms", 200)))
        except (TypeError, ValueError):
            self.poll_ms = 200
        self.ui_dark      = bool(cfg0.get("ui_dark", True))
        self.show_secondary_combat_metrics = config_bool(
            cfg0.get("show_secondary_combat_metrics"),
            False,
        )
        self.enemy_health_disclosure = config_choice(
            cfg0.get("enemy_health_disclosure"),
            ENEMY_HEALTH_DISCLOSURE_LABELS,
            "condition",
        )
        
        ov = cfg0.get("overlay") if isinstance(cfg0.get("overlay"), dict) else {}
        self.ov_screen = ov.get("screen")
        self.ov_fit    = (ov.get("fit") or "contain")
        self.ov_full   = bool(ov.get("fullscreen", True))

        self.mode = str(cfg0.get("mode", "combat") or "combat")
        self.overlay_on = False
        self.overlay_win: Optional[QtWidgets.QWidget] = None
        self._OverlayClass = Overlay
        self._shortcuts = get_shortcuts_from_config(cfg0)

        self._status_catalog = load_status_catalog()

        # Build UI from new modules
        self._build_menubar()
        self._build_toolbar()
        self._build_presentation_toolbar()

        # Tab widgets (each lives in its own dock)
        self.combat_tab = CombatTab(self)
        self.dialog_tab = DialogTab(self)
        self.notes_tab = NotesTab(self)
        self.encounters_tab = EncountersTab(self)
        self.rosters_tab = RostersTab(self)
        self.timers_tab = TimersTab(self)
        self.dice_tab = DiceTab(self)
        self.combat_tab.progressionChanged.connect(self._sync_presentation_controller)
        self.dialog_tab.progressionChanged.connect(self._sync_presentation_controller)

        self._build_dock_layout()
        self._restore_window_layout(cfg0)
        self._apply_ui_theme(self.ui_dark)

        # Rebindable shortcuts (created from config)
        self._shortcut_objects: List[QtGui.QShortcut] = []
        self._install_shortcuts()

        # initial sync
        self._sync_toolbar()
        self._sync_presentation_controller()
        if self._config_write_blocked:
            self._toast(f"Configuration was not loaded; {CONFIG_FP.name} will not be overwritten.")
        
        # allow tabs to create the dialog without import cycles
        self._StatusEditorDialog = StatusEditorDialog

    def _persist_all(self):
        self.combat_tab._persist_party()
        self.dialog_tab._persist_dialog()

    def _make_dock(self, object_name: str, title: str, widget: QtWidgets.QWidget) -> QtWidgets.QDockWidget:
        dock = QtWidgets.QDockWidget(title, self)
        dock.setObjectName(object_name)
        dock.setWidget(widget)
        dock.setFeatures(
            QtWidgets.QDockWidget.DockWidgetMovable
            | QtWidgets.QDockWidget.DockWidgetFloatable
            | QtWidgets.QDockWidget.DockWidgetClosable
        )
        dock.setAllowedAreas(
            QtCore.Qt.LeftDockWidgetArea
            | QtCore.Qt.RightDockWidgetArea
            | QtCore.Qt.TopDockWidgetArea
            | QtCore.Qt.BottomDockWidgetArea
        )
        dock.setToolTip(
            "Each panel is its own dock. Drag this title bar away to float it, "
            "or drop it on another edge to dock separately. Tabbed panels can be "
            "pulled apart by dragging their tab."
        )
        return dock

    def _build_dock_layout(self):
        """Create dockable panels; default arrangement applied if no saved state."""
        self.setDockNestingEnabled(True)
        self.setDockOptions(
            QtWidgets.QMainWindow.DockOption.AnimatedDocks
            | QtWidgets.QMainWindow.DockOption.AllowNestedDocks
            | QtWidgets.QMainWindow.DockOption.AllowTabbedDocks
        )
        self.setCorner(QtCore.Qt.TopLeftCorner, QtCore.Qt.LeftDockWidgetArea)
        self.setCorner(QtCore.Qt.BottomLeftCorner, QtCore.Qt.LeftDockWidgetArea)
        self.setCorner(QtCore.Qt.TopRightCorner, QtCore.Qt.RightDockWidgetArea)
        self.setCorner(QtCore.Qt.BottomRightCorner, QtCore.Qt.RightDockWidgetArea)

        central = QtWidgets.QWidget()
        central.setMinimumSize(1, 1)
        self.setCentralWidget(central)

        self._dock_combat = self._make_dock("dock_combat", "Combat", self.combat_tab)
        self._dock_dialog = self._make_dock("dock_dialog", "Dialog", self.dialog_tab)
        self._dock_rosters = self._make_dock("dock_rosters", "Rosters", self.rosters_tab)
        self._dock_encounters = self._make_dock("dock_encounters", "Saved Encounters", self.encounters_tab)
        self._dock_notes = self._make_dock("dock_notes", "Notes", self.notes_tab)
        self._dock_dice = self._make_dock("dock_dice", "Dice", self.dice_tab)
        self._dock_timers = self._make_dock("dock_timers", "Timers", self.timers_tab)

        self._tool_docks = [
            self._dock_rosters,
            self._dock_encounters,
            self._dock_notes,
            self._dock_dice,
            self._dock_timers,
        ]
        self._all_docks = [
            self._dock_combat,
            self._dock_dialog,
            *self._tool_docks,
        ]
        for dock in self._all_docks:
            dock.setMinimumWidth(320)
            dock.setMinimumHeight(200)

        self._populate_panels_menu()

    def _float_dock(self, dock: QtWidgets.QDockWidget):
        """Float a single dock as its own window (independent of other panels)."""
        if not dock.isVisible():
            dock.show()
        dock.setFloating(True)
        dock.resize(max(dock.width(), 420), max(dock.height(), 480))
        geo = self.frameGeometry()
        offset = 30 * (self._tool_docks.index(dock) + 1) if dock in self._tool_docks else 0
        dock.move(geo.right() - dock.width() - 24 - offset, geo.top() + 48 + offset)

    def _tabify_tool_docks(self):
        """Tab tool panels together on the right; each remains a separate dock that can be split out again."""
        anchor = self._dock_rosters
        anchor.setFloating(False)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, anchor)
        for dock in self._tool_docks:
            if dock is anchor:
                continue
            dock.setFloating(False)
            self.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
            self.tabifyDockWidget(anchor, dock)
        anchor.raise_()
        self.resizeDocks([anchor], [380], QtCore.Qt.Horizontal)

    def _populate_panels_menu(self):
        self._panels_menu.clear()
        self._panels_menu.addAction(self._dock_combat.toggleViewAction())
        self._panels_menu.addAction(self._dock_dialog.toggleViewAction())
        self._panels_menu.addSeparator()

        m_tools = self._panels_menu.addMenu("Tool panels")
        act_tab_tools = m_tools.addAction("Tab all tool panels together")
        act_tab_tools.setToolTip(
            "Groups Rosters, Encounters, Notes, Dice, and Timers into one tabbed stack. "
            "You can still drag any tab out to use it as a separate dock."
        )
        act_tab_tools.triggered.connect(self._tabify_tool_docks)
        m_tools.addSeparator()

        for dock in self._tool_docks:
            m_tools.addAction(dock.toggleViewAction())
            float_act = m_tools.addAction(f"Float “{dock.windowTitle()}” separately…")
            float_act.triggered.connect(lambda checked=False, d=dock: self._float_dock(d))

    def _apply_default_dock_layout(self):
        """Combat + Dialog stacked left; tool panels tabbed on the right (each is still its own dock)."""
        for dock in self._all_docks:
            self.removeDockWidget(dock)
            dock.setFloating(False)

        self.addDockWidget(QtCore.Qt.LeftDockWidgetArea, self._dock_combat)
        self.addDockWidget(QtCore.Qt.LeftDockWidgetArea, self._dock_dialog)
        self.splitDockWidget(self._dock_combat, self._dock_dialog, QtCore.Qt.Vertical)
        self.resizeDocks([self._dock_combat, self._dock_dialog], [520, 220], QtCore.Qt.Vertical)

        self._tabify_tool_docks()

        for dock in self._all_docks:
            dock.show()

    def _restore_window_layout(self, cfg: dict):
        win = cfg.get("window") if isinstance(cfg.get("window"), dict) else {}
        if win.get("geometry"):
            try:
                self.restoreGeometry(decode_bytes(win["geometry"]))
            except Exception:
                pass
        state_ok = False
        if win.get("state"):
            try:
                state_ok = bool(
                    self.restoreState(decode_bytes(win["state"]), WINDOW_STATE_VERSION)
                )
            except Exception:
                state_ok = False
        if not state_ok:
            self._apply_default_dock_layout()

    def _save_window_layout(self):
        cfg_result = load_json(CONFIG_FP)
        if self._config_write_blocked or (
            cfg_result.valid and not isinstance(cfg_result.data, dict)
        ) or (not cfg_result.valid and not cfg_result.missing):
            self._toast(f"Window layout not saved because {CONFIG_FP.name} is invalid.")
            return False
        cfg = dict(cfg_result.data) if cfg_result.valid else dict(self._config_document)
        cfg["window"] = {
            "geometry": encode_bytes(self.saveGeometry()),
            "state": encode_bytes(self.saveState(WINDOW_STATE_VERSION)),
        }
        write_json(CONFIG_FP, cfg)
        self._config_document = dict(cfg)
        return True

    def _reset_dock_layout(self):
        reply = QtWidgets.QMessageBox.question(
            self,
            "Reset Window Layout",
            "Restore the default panel arrangement? This cannot be undone until you rearrange panels again.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if reply == QtWidgets.QMessageBox.Yes:
            self._apply_default_dock_layout()
            self._save_window_layout()
            self._toast("Window layout reset to default.")

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
        mView.addSeparator()
        actShortcuts = mView.addAction("Keyboard Shortcuts…")
        actShortcuts.triggered.connect(self._open_shortcuts_editor)
        mPanels = mView.addMenu("Panels")
        self._panels_menu = mPanels
        mView.addSeparator()
        actResetLayout = mView.addAction("Reset Window Layout…")
        actResetLayout.triggered.connect(self._reset_dock_layout)

        # Overlay
        mOverlay = mb.addMenu("&Overlay")
        actReload = mOverlay.addAction("Reload Now"); actReload.triggered.connect(self._reload_now)
        self.actAutoRefresh = mOverlay.addAction("Auto Refresh")
        self.actAutoRefresh.setCheckable(True)
        self.actAutoRefresh.setChecked(self.auto_refresh)
        self.actAutoRefresh.toggled.connect(self._set_auto_refresh)
        self.actShowSecondaryMetrics = mOverlay.addAction("Show secondary combat metrics")
        self.actShowSecondaryMetrics.setCheckable(True)
        self.actShowSecondaryMetrics.setChecked(self.show_secondary_combat_metrics)
        self.actShowSecondaryMetrics.toggled.connect(self._set_show_secondary_combat_metrics)
        enemy_health_menu = mOverlay.addMenu("Enemy Health Disclosure")
        enemy_health_group = QtGui.QActionGroup(self)
        enemy_health_group.setExclusive(True)
        self._enemy_health_actions = {}
        for disclosure, label in ENEMY_HEALTH_DISCLOSURE_LABELS.items():
            action = enemy_health_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(disclosure == self.enemy_health_disclosure)
            action.triggered.connect(
                lambda checked, selected=disclosure: (
                    self._set_enemy_health_disclosure(selected) if checked else None
                )
            )
            enemy_health_group.addAction(action)
            self._enemy_health_actions[disclosure] = action
        actInterval = mOverlay.addAction("Set Refresh Interval…")
        actInterval.triggered.connect(self._set_poll_interval)
        self._themes_menu = mOverlay.addMenu("Overlay Theme")
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
        tb.setObjectName("toolbar_main")
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
        self.lblOverlayTheme = QtWidgets.QLabel("Overlay Theme:")
        tb.addWidget(self.lblOverlayTheme)
        self.cmbTheme = QtWidgets.QComboBox()
        self.cmbTheme.setMinimumWidth(220)
        self.cmbTheme.setAccessibleName("Overlay Theme")
        self.cmbTheme.setToolTip("Select the player-facing overlay theme")
        self.cmbTheme.setItemDelegate(ThemePreviewDelegate(self.cmbTheme, THEMES_DIR))
        self._populate_themes_combo()
        theme_index = self.cmbTheme.findData(self.theme_name)
        if theme_index >= 0:
            self.cmbTheme.setCurrentIndex(theme_index)
        self.cmbTheme.currentTextChanged.connect(self._set_theme_from_combo)
        tb.addWidget(self.cmbTheme)

    def _build_presentation_toolbar(self):
        self.addToolBarBreak(QtCore.Qt.ToolBarArea.TopToolBarArea)
        toolbar = QtWidgets.QToolBar("Presentation", self)
        toolbar.setObjectName("toolbar_presentation")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.addToolBar(QtCore.Qt.ToolBarArea.TopToolBarArea, toolbar)
        self.btnPresentationPrevious = QtWidgets.QToolButton()
        self.btnPresentationPrevious.setText("◀")
        self.btnPresentationPrevious.setAccessibleName("Previous presentation item")
        self.btnPresentationPrevious.setToolTip(
            "Move backward in the explicit live presentation mode"
        )
        self.btnPresentationPrevious.clicked.connect(self._prev_mode)
        toolbar.addWidget(self.btnPresentationPrevious)
        self.lblPresentationStatus = QtWidgets.QLabel("Combat · Round 1 · — → —")
        self.lblPresentationStatus.setAccessibleName("Live presentation status")
        self.lblPresentationStatus.setMinimumWidth(280)
        self.lblPresentationStatus.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.lblPresentationStatus.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Preferred,
        )
        toolbar.addWidget(self.lblPresentationStatus)
        self.btnPresentationNext = QtWidgets.QToolButton()
        self.btnPresentationNext.setText("▶")
        self.btnPresentationNext.setAccessibleName("Next presentation item")
        self.btnPresentationNext.setToolTip(
            "Move forward in the explicit live presentation mode"
        )
        self.btnPresentationNext.clicked.connect(self._advance_mode)
        toolbar.addWidget(self.btnPresentationNext)

    def _sync_presentation_controller(self):
        if not hasattr(self, "lblPresentationStatus"):
            return
        if self.mode == "dialog":
            blocks = getattr(self.dialog_tab, "dialog_blocks", [])
            index = getattr(self.dialog_tab, "dialog_index", -1)
            if 0 <= index < len(blocks):
                speaker = str(blocks[index].get("speaker") or "Narrator")
                status = f"Dialog · {index + 1}/{len(blocks)} · {speaker}"
            else:
                status = f"Dialog · none active · {len(blocks)} prepared"
            self.btnPresentationPrevious.setEnabled(index > 0)
            self.btnPresentationNext.setEnabled(
                bool(blocks) and index < len(blocks) - 1
            )
        else:
            combatants = getattr(self.combat_tab, "combatants", [])
            index = getattr(self.combat_tab, "turn_index", -1)
            round_number = max(1, getattr(self.combat_tab, "round", 1))
            current = (
                str(combatants[index].get("name") or "Unnamed")
                if 0 <= index < len(combatants)
                else "—"
            )
            if combatants:
                next_index = 0 if index >= len(combatants) - 1 else max(0, index + 1)
                following = str(combatants[next_index].get("name") or "Unnamed")
                next_round = round_number + 1 if index == len(combatants) - 1 else round_number
                suffix = f" (R{next_round})" if next_round != round_number else ""
                following += suffix
            else:
                following = "—"
            status = f"Combat · Round {round_number} · {current} → {following}"
            self.btnPresentationPrevious.setEnabled(
                bool(combatants) and index >= 0 and (index > 0 or round_number > 1)
            )
            self.btnPresentationNext.setEnabled(bool(combatants))
        self.lblPresentationStatus.setText(status)
        self.lblPresentationStatus.setToolTip(status)
        self.lblPresentationStatus.setAccessibleName(status)

    def _advance_mode(self):
        if self.mode == "combat":
            self.combat_tab._advance_combat_next()
        elif self.mode == "dialog":
            self.dialog_tab._dialog_next_local()
        self._sync_presentation_controller()

    def _prev_mode(self):
        if self.mode == "combat":
            self.combat_tab._advance_combat_prev()
        elif self.mode == "dialog":
            self.dialog_tab._dialog_prev_local()
        self._sync_presentation_controller()

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
        cfg_result = load_json(CONFIG_FP)
        if self._config_write_blocked or (
            cfg_result.valid and not isinstance(cfg_result.data, dict)
        ) or (not cfg_result.valid and not cfg_result.missing):
            self._toast(f"Settings not saved because {CONFIG_FP.name} is invalid.")
            return False
        cfg = dict(cfg_result.data) if cfg_result.valid else dict(self._config_document)
        overlay = cfg.get("overlay")
        overlay = dict(overlay) if isinstance(overlay, dict) else {}
        overlay.update({
            "screen": self.ov_screen,
            "fit": self.ov_fit,
            "fullscreen": self.ov_full,
        })
        cfg.update({
            "theme": self.theme_name,
            "auto_refresh": self.auto_refresh,
            "poll_ms": self.poll_ms,
            "ui_dark": self.ui_dark,
            "mode": self.mode,  # "combat" or "dialog" - controls overlay display
            "show_secondary_combat_metrics": self.show_secondary_combat_metrics,
            "enemy_health_disclosure": config_choice(
                getattr(self, "enemy_health_disclosure", "condition"),
                ENEMY_HEALTH_DISCLOSURE_LABELS,
                "condition",
            ),
            "shortcuts": self._shortcuts,
            "overlay": overlay,
        })
        write_json(CONFIG_FP, cfg)
        self._config_document = dict(cfg)
        return True

    def _install_shortcuts(self):
        for s in self._shortcut_objects:
            s.setEnabled(False)
            s.deleteLater()
        self._shortcut_objects.clear()
        actions = {
            "toggle_overlay": self._toggle_overlay_hotkey,
            "advance_turn": self._advance_mode,
            "previous_turn": self._prev_mode,
            "toggle_mode": self._toggle_mode,
            "focus_search": self._focus_active_search,
            "add_dialog": self._add_dialog_block,
            "make_dialog_current": self._dialog_make_current,
        }
        for key, seq_str in self._shortcuts.items():
            if not seq_str or key not in actions:
                continue
            try:
                seq = QtGui.QKeySequence(seq_str)
                if seq.isEmpty():
                    continue
                shortcut = QtGui.QShortcut(seq, self, activated=actions[key])
                self._shortcut_objects.append(shortcut)
            except Exception:
                pass

    def _open_shortcuts_editor(self):
        dlg = ShortcutEditorDialog(self, self._shortcuts, self._on_shortcuts_saved)
        dlg.exec()

    def _on_shortcuts_saved(self, new_shortcuts: Dict[str, str]):
        self._shortcuts = dict(new_shortcuts)
        self._persist_config()
        self._install_shortcuts()
        self._toast("Shortcuts updated.")

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
        for theme_id in names:
            self.cmbTheme.addItem(OVERLAY_THEME_LABELS.get(theme_id, theme_id), theme_id)

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
        for theme_id in names:
            act = self._themes_menu.addAction(
                OVERLAY_THEME_LABELS.get(theme_id, theme_id)
            )
            act.setData(theme_id)
            act.setCheckable(True)
            act.setChecked(theme_id == self.theme_name)
            act.triggered.connect(
                lambda checked, selected_id=theme_id: self._select_overlay_theme_id(selected_id)
            )
            group.addAction(act)

    def _select_overlay_theme_id(self, theme_id: str):
        index = self.cmbTheme.findData(theme_id)
        if index >= 0:
            self.cmbTheme.setCurrentIndex(index)

    def _set_theme_from_combo(self, display_name: str):
        index = self.cmbTheme.currentIndex()
        theme_id = self.cmbTheme.itemData(index) if index >= 0 else None
        if not theme_id:
            return
        self.theme_name = str(theme_id).strip()
        self._persist_config()
        # immediately push theme change to overlay if running
        if self.overlay_win:
            self.overlay_win.theme_name = self.theme_name
            self.overlay_win.theme = self.overlay_win._load_theme()
            self.overlay_win.repaint()
        for act in self._themes_menu.actions():
            act.setChecked(act.data() == self.theme_name)
        label = OVERLAY_THEME_LABELS.get(self.theme_name, display_name)
        self._toast(f"Overlay theme set to '{label}'.")

    def _update_mode_button_text(self):
        self.btnMode.setText(f"Mode: {'Combat' if self.btnMode.isChecked() else 'Dialog'}")

    def _mode_button_toggled(self, checked: bool):
        self.mode = "combat" if checked else "dialog"
        self._update_mode_button_text()
        self._persist_config()
        self._toast(f"Mode → {self.mode.capitalize()}")
        self._sync_presentation_controller()
        # Immediately push mode change to overlay if running
        if self.overlay_win:
            if hasattr(self.overlay_win, "set_presentation_mode"):
                self.overlay_win.set_presentation_mode(self.mode)
            else:
                self.overlay_win.mode = self.mode
                self.overlay_win.repaint()

    def _set_overlay(self, on: bool):
        self.overlay_on = on
        self.btnOverlay.setText("Overlay ON" if on else "Overlay OFF")
        if on:
            try:
                if not self.overlay_win:
                    overlay_runtime_log("GM requested overlay creation")
                    self.overlay_win = self._OverlayClass(
                        theme_name=self.theme_name,
                        fit_mode=self.ov_fit,
                    )
                    overlay_runtime_log("GM overlay window created")
                self.overlay_win.show_secondary_combat_metrics = self.show_secondary_combat_metrics
                self.overlay_win.enemy_health_disclosure = self.enemy_health_disclosure
                self.overlay_win.move_to_screen(self.ov_screen)
                if self.ov_full:
                    self.overlay_win.showFullScreen()
                    overlay_runtime_log("GM overlay shown fullscreen")
                else:
                    self.overlay_win.show()
                    overlay_runtime_log("GM overlay shown windowed")
            except Exception as error:
                overlay_runtime_log("GM overlay initialization failed", error)
                self.overlay_win = None
                self.overlay_on = False
                self.btnOverlay.blockSignals(True)
                self.btnOverlay.setChecked(False)
                self.btnOverlay.blockSignals(False)
                self.btnOverlay.setText("Overlay OFF")
                self._toast(
                    "Overlay could not be started. See the EncounterOS overlay log."
                )
        elif self.overlay_win:
            self.overlay_win.hide()
            overlay_runtime_log("GM overlay hidden")

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

    def _set_show_secondary_combat_metrics(self, on: bool):
        self.show_secondary_combat_metrics = bool(on)
        self._persist_config()
        if self.overlay_win:
            self.overlay_win.show_secondary_combat_metrics = self.show_secondary_combat_metrics
            self.overlay_win.repaint()
        self._toast(f"Secondary combat metrics {'shown' if on else 'hidden'}.")

    def _set_enemy_health_disclosure(self, disclosure: str):
        selected = config_choice(
            disclosure,
            ENEMY_HEALTH_DISCLOSURE_LABELS,
            "condition",
        )
        if selected == self.enemy_health_disclosure:
            return
        self.enemy_health_disclosure = selected
        self._persist_config()
        if self.overlay_win:
            self.overlay_win.enemy_health_disclosure = selected
            self.overlay_win.repaint()
        self._toast(
            "Enemy health disclosure: "
            f"{ENEMY_HEALTH_DISCLOSURE_LABELS[selected]}."
        )

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
            old = self.btnOverlay.blockSignals(True)
            self.btnOverlay.setChecked(self.overlay_on)
            self.btnOverlay.blockSignals(old)
        if hasattr(self, "btnMode"):
            old = self.btnMode.blockSignals(True)
            self.btnMode.setChecked(self.mode == "combat")
            self.btnMode.blockSignals(old)
            self._update_mode_button_text()
        if hasattr(self, "cmbTheme"):
            idx = self.cmbTheme.findData(self.theme_name)
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
        if hasattr(self, "actShowSecondaryMetrics"):
            old = self.actShowSecondaryMetrics.blockSignals(True)
            self.actShowSecondaryMetrics.setChecked(self.show_secondary_combat_metrics)
            self.actShowSecondaryMetrics.blockSignals(old)
        for disclosure, action in getattr(
            self, "_enemy_health_actions", {}
        ).items():
            old = action.blockSignals(True)
            action.setChecked(disclosure == self.enemy_health_disclosure)
            action.blockSignals(old)
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
                if not self.notes_tab._save_note():
                    a.ignore()
                    return
            elif reply == QtWidgets.QMessageBox.Cancel:
                a.ignore()
                return
        
        self._save_window_layout()
        if self.overlay_win:
            overlay_runtime_log("GM overlay closing with application")
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
        theme_label = index.data(QtCore.Qt.DisplayRole) or ""
        theme_id = index.data(QtCore.Qt.UserRole) or theme_label
        color_hex = self._theme_preview_color(theme_id)
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
        painter.drawText(text_rect, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, theme_label)


# Entity Dialog Class
class EntityDialog(QtWidgets.QDialog):
    def __init__(self, parent: GMWindow, data: Dict):
        super().__init__(parent)
        self.setWindowTitle(f"Edit Entity: {data.get('name', 'New')}")
        self.setMinimumWidth(520)
        self.data = data
        self.parent = parent
        self.combat_metric = resolve_combat_metric(data or {})
        self.secondary_metric = resolve_secondary_combat_metric(data or {})
        warning = secondary_metric_warning(data or {})
        if warning and hasattr(parent, "_log"):
            parent._log(warning)
        
        f = QtWidgets.QFormLayout(self)
        self.edName = QtWidgets.QLineEdit(); self.edName.setText(data.get("name", "New Creature"))
        metric_max = (data or {}).get(self.combat_metric.max_field)
        if metric_max is None:
            metric_max = (data or {}).get(self.combat_metric.field, 1)
        self.edHP = QtWidgets.QSpinBox()
        self.edHP.setRange(0, 9999)
        self.edHP.setValue(max(0, coerce_metric_int(metric_max, 1)))
        self.cbSide = QtWidgets.QComboBox()
        self.cbSide.addItems(["Friendly", "Neutral", "Enemy"])
        self.cbSide.setCurrentIndex(["Friendly", "Neutral", "Enemy"].index(data.get("side", "Enemy")))
        self.edInit = QtWidgets.QSpinBox(); self.edInit.setRange(-50, 50); self.edInit.setValue(int((data or {}).get("initMod", (data or {}).get("initiative", 0))))

        f.addRow("Name", self.edName)
        f.addRow(f"{self.combat_metric.label} (max)", self.parent._wrap_spin_with_nudgers(self.edHP))
        if self.secondary_metric:
            secondary_current, secondary_max = metric_values(data or {}, self.secondary_metric)
            self.edSecondary = QtWidgets.QSpinBox()
            self.edSecondary.setRange(0, 9999)
            self.edSecondary.setValue(secondary_current)
            self.edSecondaryMax = QtWidgets.QSpinBox()
            self.edSecondaryMax.setRange(0, 9999)
            self.edSecondaryMax.setValue(secondary_max)
            f.addRow(self.secondary_metric.label, self.parent._wrap_spin_with_nudgers(self.edSecondary))
            f.addRow(f"{self.secondary_metric.label} (max)", self.parent._wrap_spin_with_nudgers(self.edSecondaryMax))
        f.addRow("Side", self.cbSide)
        self.portraitLibrary = PortraitLibraryWidget(data or {}, self)
        f.addRow(self.portraitLibrary)
        f.addRow("Initiative (roll)", self.parent._wrap_spin_with_nudgers(self.edInit))
        
        box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok|QtWidgets.QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept); box.rejected.connect(self.reject)
        f.addRow(box)

    def payload(self) -> Dict:
        metric = getattr(
            self,
            "combat_metric",
            getattr(self, "metric", resolve_combat_metric(self.data or {})),
        )
        metric_max = int(self.edHP.value())
        payload = dict(self.data or {})
        if payload.get(metric.field) is None:
            payload[metric.field] = metric_max
        payload[metric.max_field] = metric_max
        secondary = getattr(self, "secondary_metric", None)
        if secondary and hasattr(self, "edSecondary") and hasattr(self, "edSecondaryMax"):
            payload[secondary.field] = int(self.edSecondary.value())
            payload[secondary.max_field] = int(self.edSecondaryMax.value())
        portrait_library = getattr(self, "portraitLibrary", None)
        if portrait_library is not None:
            portraits = portrait_library.portraits()
            payload["portraits"] = portraits
            payload["portrait"] = portraits[0].get("file") if portraits else None
            if portraits and not payload.get("id"):
                payload["id"] = str(uuid4())
        else:
            # Compatibility for lightweight callers and older test harnesses.
            portrait_editor = getattr(self, "edPortrait", None)
            if portrait_editor is not None:
                payload["portrait"] = portrait_editor.text().strip() or None
        payload.update({
            "name": self.edName.text().strip(),
            "initMod": int(self.edInit.value()),
            "initTotal": (self.data or {}).get("initTotal"),
            "initRoll": (self.data or {}).get("initRoll"),
            "notes": (self.data or {}).get("notes", ""),
            "statuses": (self.data or {}).get("statuses", []),
            "side": self.cbSide.currentText(),
        })
        return payload

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
