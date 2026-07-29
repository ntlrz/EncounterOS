from __future__ import annotations
from PySide6 import QtWidgets, QtGui, QtCore
from typing import Dict, List, Any
import json
from copy import deepcopy
from uuid import uuid4

from helpers import load_json, roll_d20, write_json, collect_suffixes, next_suffix
from app_paths import PARTY_FP, SESSION_ROSTER_FP
from combat_metrics import (
    coerce_metric_int,
    metric_conflict_warning,
    metric_values,
    resolve_combat_metric,
    resolve_secondary_combat_metric,
)
from portrait_library import PORTRAIT_SOURCE_DIR_FIELD, resolve_entity_portrait


COMBAT_ENTITY_ROLE = int(QtCore.Qt.ItemDataRole.UserRole)
COMBAT_ACTIVE_ROLE = COMBAT_ENTITY_ROLE + 1
COMBAT_PORTRAIT_ROLE = COMBAT_ENTITY_ROLE + 2
COMBAT_ROW_INDEX_ROLE = COMBAT_ENTITY_ROLE + 3
COMBAT_INSTANCE_ID_FIELD = "_combat_instance_id"


def ensure_live_combat_instance_ids(combatants: List[Dict]) -> None:
    """Assign unique live-instance IDs without touching source documents."""
    used: set[str] = set()
    for combatant in combatants:
        value = combatant.get(COMBAT_INSTANCE_ID_FIELD)
        if not isinstance(value, str) or not value.strip() or value in used:
            value = str(uuid4())
            combatant[COMBAT_INSTANCE_ID_FIELD] = value
        used.add(value)


def live_combatant_index(combatants: List[Dict], instance_id: str | None) -> int:
    if not instance_id:
        return -1
    return next(
        (
            index
            for index, combatant in enumerate(combatants)
            if combatant.get(COMBAT_INSTANCE_ID_FIELD) == instance_id
        ),
        -1,
    )


def combat_row_height(width: int, has_secondary: bool = False) -> int:
    """Single-line operational row height at standard application scaling."""
    return 40


def combat_row_geometry(
    bounds: QtCore.QRect,
    *,
    has_secondary: bool = False,
) -> dict[str, Any]:
    """Stable single-line columns used by production painting and tests."""
    card = bounds.adjusted(1, 0, -1, -1)
    line = card.adjusted(5, 3, -5, -3)
    x = line.left()
    indicator = QtCore.QRect(x, line.top(), 16, line.height())
    x = indicator.right() + 3
    side = QtCore.QRect(x, line.top(), 18, line.height())
    x = side.right() + 4
    portrait_size = min(32, line.height())
    portrait = QtCore.QRect(
        x,
        line.center().y() - portrait_size // 2,
        portrait_size,
        portrait_size,
    )
    x = portrait.right() + 7

    initiative_width = 54
    metric_width = 150 if card.width() >= 800 else 118
    conditions_width = min(
        250,
        max(76, int(card.width() * (0.23 if card.width() >= 700 else 0.18))),
    )
    right = line.right()
    conditions = QtCore.QRect(
        right - conditions_width + 1,
        line.top(),
        conditions_width,
        line.height(),
    )
    right = conditions.left() - 8
    primary = QtCore.QRect(
        right - metric_width + 1,
        line.top(),
        metric_width,
        line.height(),
    )
    right = primary.left() - 8
    initiative = QtCore.QRect(
        right - initiative_width + 1,
        line.top(),
        initiative_width,
        line.height(),
    )
    right = initiative.left() - 8
    if right - x + 1 < 100:
        reclaim = min(conditions.width() - 48, 100 - (right - x + 1))
        conditions.setLeft(conditions.left() + max(0, reclaim))
        primary.moveRight(conditions.left() - 8)
        initiative.moveRight(primary.left() - 8)
        right = initiative.left() - 8
    name = QtCore.QRect(x, line.top(), max(36, right - x + 1), line.height())

    return {
        "card": card,
        "indicator": indicator,
        "side": side,
        "portrait": portrait,
        "name": name,
        "initiative": initiative,
        "primary": primary,
        "secondary": QtCore.QRect(),
        "conditions": conditions,
        "actions": {},
        "narrow": bounds.width() < 700,
        "full_actions": False,
    }


def _color_with_alpha(color: QtGui.QColor, alpha: int) -> QtGui.QColor:
    result = QtGui.QColor(color)
    result.setAlpha(alpha)
    return result


class CombatListWidget(QtWidgets.QListWidget):
    viewportResized = QtCore.Signal()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.viewportResized.emit()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.count():
            return
        painter = QtGui.QPainter(self.viewport())
        painter.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing)
        text = "No combatants in this encounter.\nAdd a combatant or load an encounter to begin."
        color = self.palette().color(QtGui.QPalette.ColorRole.PlaceholderText)
        painter.setPen(color)
        painter.drawText(
            self.viewport().rect().adjusted(24, 24, -24, -24),
            QtCore.Qt.AlignmentFlag.AlignCenter,
            text,
        )


class ElidedLabel(QtWidgets.QLabel):
    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        text = self.fontMetrics().elidedText(
            self.text(),
            QtCore.Qt.TextElideMode.ElideRight,
            max(0, self.contentsRect().width()),
        )
        painter.setPen(self.palette().color(QtGui.QPalette.ColorRole.WindowText))
        painter.drawText(
            self.contentsRect(),
            self.alignment() | QtCore.Qt.AlignmentFlag.AlignVCenter,
            text,
        )


class CombatRowDelegate(QtWidgets.QStyledItemDelegate):
    """Compact operational combat row with production geometry hit testing."""

    def __init__(self, tab: "CombatTab"):
        super().__init__(tab.listCombat)
        self.tab = tab

    def sizeHint(self, option, index):
        entity = index.data(COMBAT_ENTITY_ROLE) or {}
        secondary = resolve_secondary_combat_metric(entity)
        has_secondary = bool(secondary and secondary.field in entity)
        width = self.tab.listCombat.viewport().width()
        return QtCore.QSize(max(300, width - 2), combat_row_height(width, has_secondary))

    @staticmethod
    def condition_summary(statuses, width, metrics):
        values = [str(value).strip() for value in statuses if str(value).strip()]
        if not values:
            return "—"
        full = ", ".join(values)
        if metrics.horizontalAdvance(full) <= width:
            return full
        for shown_count in range(len(values) - 1, 0, -1):
            hidden = len(values) - shown_count
            candidate = f"{', '.join(values[:shown_count])}, +{hidden} more"
            if metrics.horizontalAdvance(candidate) <= width:
                return candidate
        return metrics.elidedText(
            values[0],
            QtCore.Qt.TextElideMode.ElideRight,
            width,
        )

    def paint(self, painter, option, index):
        entity = index.data(COMBAT_ENTITY_ROLE) or {}
        active = bool(index.data(COMBAT_ACTIVE_ROLE))
        selected = bool(option.state & QtWidgets.QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QtWidgets.QStyle.StateFlag.State_MouseOver)
        geometry = combat_row_geometry(option.rect)
        card = geometry["card"]
        palette = option.palette
        base = palette.color(QtGui.QPalette.ColorRole.Base)
        text = palette.color(QtGui.QPalette.ColorRole.Text)
        accent = QtGui.QColor("#d6a34a" if self.tab.parent.ui_dark else "#9a6700")
        selection = palette.color(QtGui.QPalette.ColorRole.Highlight)
        side_value = str(entity.get("side") or "Enemy").strip().casefold()
        friendly = side_value in {"friendly", "ally", "allies"}
        enemy = side_value in {"enemy", "opponent", "opponents"}
        side_accent = (
            QtGui.QColor("#6f9b78" if self.tab.parent.ui_dark else "#43744d")
            if friendly
            else QtGui.QColor("#a56d6d" if self.tab.parent.ui_dark else "#8a4b4b")
            if enemy
            else palette.color(QtGui.QPalette.ColorRole.Mid)
        )
        side_label = "A" if friendly else "E" if enemy else "N"

        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        background = base
        if active:
            background = _color_with_alpha(accent, 35)
        elif selected:
            background = _color_with_alpha(selection, 48)
        elif hovered:
            background = _color_with_alpha(palette.color(QtGui.QPalette.ColorRole.Mid), 40)
        painter.setBrush(background)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.drawRect(card)
        painter.setPen(QtGui.QPen(_color_with_alpha(palette.color(QtGui.QPalette.ColorRole.Mid), 110), 1))
        painter.drawLine(card.bottomLeft(), card.bottomRight())
        if selected:
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.setPen(QtGui.QPen(selection, 1))
            painter.drawRect(card.adjusted(1, 1, -1, -1))
        if active:
            painter.setPen(accent)
            active_font = painter.font()
            active_font.setBold(True)
            painter.setFont(active_font)
            painter.drawText(
                geometry["indicator"],
                QtCore.Qt.AlignmentFlag.AlignCenter,
                "▶",
            )

        painter.setPen(side_accent)
        side_font = painter.font()
        side_font.setBold(True)
        side_font.setPointSizeF(max(8.0, side_font.pointSizeF() - 1))
        painter.setFont(side_font)
        painter.drawText(geometry["side"], QtCore.Qt.AlignmentFlag.AlignCenter, side_label)

        portrait = geometry["portrait"]
        pixmap = index.data(COMBAT_PORTRAIT_ROLE)
        if isinstance(pixmap, QtGui.QPixmap) and not pixmap.isNull():
            clipped = pixmap.scaled(
                portrait.size(),
                QtCore.Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
            painter.save()
            path = QtGui.QPainterPath()
            path.addRoundedRect(QtCore.QRectF(portrait), 5, 5)
            painter.setClipPath(path)
            painter.drawPixmap(portrait, clipped)
            painter.restore()
        else:
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.setPen(QtGui.QPen(_color_with_alpha(side_accent, 150), 1))
            painter.drawRoundedRect(portrait, 3, 3)
            painter.setPen(palette.color(QtGui.QPalette.ColorRole.PlaceholderText))
            painter.drawText(portrait, QtCore.Qt.AlignmentFlag.AlignCenter, "—")
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.setPen(QtGui.QPen(side_accent, 1))
        painter.drawRoundedRect(portrait, 3, 3)

        font = painter.font()
        font.setBold(True)
        font.setPointSizeF(max(9.0, font.pointSizeF()))
        painter.setFont(font)
        painter.setPen(text)
        name = str(entity.get("name") or "Unnamed combatant")
        name_metrics = QtGui.QFontMetrics(font)
        painter.drawText(
            geometry["name"],
            QtCore.Qt.AlignmentFlag.AlignVCenter,
            name_metrics.elidedText(
                name, QtCore.Qt.TextElideMode.ElideRight, geometry["name"].width()
            ),
        )

        initiative = entity.get("initTotal")
        painter.setFont(option.font)
        painter.setPen(palette.color(QtGui.QPalette.ColorRole.PlaceholderText))
        painter.drawText(
            geometry["initiative"],
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter,
            f"Init {initiative if initiative is not None else '—'}",
        )
        primary_metric = resolve_combat_metric(entity)
        current, maximum = metric_values(entity, primary_metric)
        metric_text = f"{primary_metric.label} {current}/{maximum}"
        metric_font = QtGui.QFont(option.font)
        metric_font.setBold(True)
        painter.setFont(metric_font)
        painter.setPen(text)
        painter.drawText(
            geometry["primary"],
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter,
            QtGui.QFontMetrics(metric_font).elidedText(
                metric_text,
                QtCore.Qt.TextElideMode.ElideRight,
                geometry["primary"].width(),
            ),
        )
        condition_font = QtGui.QFont(option.font)
        condition_font.setPointSizeF(max(8.0, condition_font.pointSizeF() - 0.5))
        painter.setFont(condition_font)
        painter.setPen(palette.color(QtGui.QPalette.ColorRole.Text))
        condition_metrics = QtGui.QFontMetrics(condition_font)
        condition_text = self.condition_summary(
            entity.get("statuses") or [],
            geometry["conditions"].width(),
            condition_metrics,
        )
        painter.drawText(
            geometry["conditions"],
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter,
            condition_text,
        )
        painter.restore()

    def editorEvent(self, event, model, option, index):
        if event.type() == QtCore.QEvent.Type.MouseButtonDblClick:
            self.tab._edit_combatant(index.row())
            return True
        return False


def parse_party_document(data: Any) -> tuple[Dict, List[Dict], int, int]:
    if not isinstance(data, dict):
        raise ValueError("party document must be a JSON object")
    party = data.get("party", [])
    if not isinstance(party, list) or not all(isinstance(member, dict) for member in party):
        raise ValueError("'party' must be a list of objects")
    turn_index = data.get("turn_index", -1)
    round_number = data.get("round", 1)
    if not isinstance(turn_index, int) or isinstance(turn_index, bool):
        raise ValueError("'turn_index' must be an integer")
    if not isinstance(round_number, int) or isinstance(round_number, bool):
        raise ValueError("'round' must be an integer")
    return dict(data), [dict(member) for member in party], turn_index, round_number


class CombatTab(QtWidgets.QWidget):
    progressionChanged = QtCore.Signal()

    def __init__(self, parent: QtWidgets.QMainWindow):
        super().__init__()
        self.parent = parent
        self.combatants: List[Dict] = []
        self.turn_index: int = -1
        self.round: int = 1
        self._party_document: Dict = {}
        self._party_write_blocked = False
        self._party_write_warning_shown = False
        self._metric_conflict_warnings = set()
        self._combat_portrait_cache: Dict[str, QtGui.QPixmap | None] = {}
        
        self._build_ui()
        self._wire_signals()
        
        self._load_party()

    def _build_ui(self):
        v_layout = QtWidgets.QVBoxLayout(self)
        v_layout.setContentsMargins(8, 8, 8, 8)
        v_layout.setSpacing(7)
        self.setStyleSheet(
            """
            QPushButton[combatCompact="true"] {
                padding: 5px 8px;
                min-height: 20px;
                min-width: 28px;
            }
            """
        )
        
        # Search & Add Section
        h_search = QtWidgets.QHBoxLayout()
        self.searchCombat = QtWidgets.QLineEdit()
        self.searchCombat.setPlaceholderText("Quick Add: Goblin")
        self.searchCombat.returnPressed.connect(self._add_from_search)  # Enter key support
        self.btnQuickAdd = QtWidgets.QPushButton("Add")
        self.btnQuickAdd.clicked.connect(self._add_from_search)
        self.spin_add = QtWidgets.QSpinBox()
        self.spin_add.setRange(1, 99)
        self.spin_add.setValue(1)
        self.btnCreateCharacter = QtWidgets.QPushButton("Add Combatant…")
        self.btnCreateCharacter.setToolTip(
            "Create an ad hoc combatant or choose entries from the Rosters module"
        )
        add_menu = QtWidgets.QMenu(self.btnCreateCharacter)
        add_menu.addAction("Create New…", self._create_character)
        add_menu.addAction("Choose from Rosters…", self._open_rosters_module)
        self.btnCreateCharacter.setMenu(add_menu)
        h_search.addWidget(self.searchCombat)
        h_search.addWidget(self.btnQuickAdd)
        h_search.addWidget(QtWidgets.QLabel("Qty:"))
        h_search.addWidget(self.spin_add)
        h_search.addWidget(self.btnCreateCharacter)
        v_layout.addLayout(h_search)

        # Initiative & primary combat metric tools
        h_tools = QtWidgets.QHBoxLayout()
        self.btnRollInit = QtWidgets.QPushButton("Roll Initiative")
        self.btnSortInit = QtWidgets.QPushButton("Sort Initiative")
        self.btnCombatMore = QtWidgets.QPushButton("More ▾")
        self.btnRollInit.setToolTip("Roll initiative for every combatant")
        self.btnSortInit.setToolTip("Sort combatants by their current initiative")
        combat_menu = QtWidgets.QMenu(self.btnCombatMore)
        combat_menu.addAction("Load Session", self._load_session_roster)
        combat_menu.addAction("Save Session", self._save_session_roster)
        combat_menu.addSeparator()
        combat_menu.addAction("Clear All…", self._clear_combat)
        self.btnCombatMore.setMenu(combat_menu)
        h_tools.addWidget(self.btnRollInit)
        h_tools.addWidget(self.btnSortInit)
        h_tools.addStretch(1)
        h_tools.addWidget(self.btnCombatMore)
        v_layout.addLayout(h_tools)
        
        # Combat List
        self.listCombat = CombatListWidget()
        self.listCombat.setAccessibleName("Combatants")
        self.listCombat.setAccessibleDescription(
            "Combatant rows. Active turn, selection, and hover are shown independently."
        )
        self.listCombat.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.listCombat.setAlternatingRowColors(False)
        self.listCombat.setUniformItemSizes(False)
        self.listCombat.setWordWrap(False)
        self.listCombat.setMouseTracking(True)
        self.listCombat.setVerticalScrollMode(
            QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.listCombat.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.listCombat.setContextMenuPolicy(
            QtCore.Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._combat_delegate = CombatRowDelegate(self)
        self.listCombat.setItemDelegate(self._combat_delegate)
        v_layout.addWidget(self.listCombat)
        
        # Selected-combatant strip
        selected_strip = QtWidgets.QWidget()
        selected_strip.setObjectName("combatSelectedStrip")
        selected_layout = QtWidgets.QGridLayout(selected_strip)
        selected_layout.setContentsMargins(6, 3, 6, 3)
        selected_layout.setSpacing(5)
        self.lblSelectedCombatant = ElidedLabel("Selected: none")
        self.lblSelectedCombatant.setMinimumWidth(140)
        self.lblSelectedCombatant.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Preferred,
        )
        self.btnEdit = QtWidgets.QPushButton("Edit")
        self.btnStatuses = QtWidgets.QPushButton("Conditions")
        self.btnMakeCurrent = QtWidgets.QPushButton("Make Current")
        self.btnSelectedMore = QtWidgets.QPushButton("More ▾")
        selected_more = QtWidgets.QMenu(self.btnSelectedMore)
        adjust_menu = selected_more.addMenu("Adjust Primary Metric")
        for label, delta in (("Damage 5", -5), ("Damage 1", -1), ("Heal 1", 1), ("Heal 5", 5)):
            adjust_menu.addAction(
                label,
                lambda checked=False, value=delta: self._adjust_hp_selected(value),
            )
        adjust_menu.addAction("Set Current Value…", self._set_selected_metric)
        selected_more.addSeparator()
        selected_more.addAction("Duplicate", self._duplicate_selected)
        selected_more.addAction("Remove", self._remove_selected)
        self.btnSelectedMore.setMenu(selected_more)
        selected_layout.addWidget(self.lblSelectedCombatant, 0, 0, 1, 4)
        selected_layout.addWidget(self.btnEdit, 1, 0)
        selected_layout.addWidget(self.btnStatuses, 1, 1)
        selected_layout.addWidget(self.btnMakeCurrent, 1, 2)
        selected_layout.addWidget(self.btnSelectedMore, 1, 3)
        selected_layout.setColumnStretch(4, 1)
        self.btnEdit.setToolTip("Edit the selected combatant (Enter)")
        self.btnStatuses.setToolTip("Manage conditions for the selected combatant")
        self.btnMakeCurrent.setToolTip(
            "Explicitly make the selected combatant current on the player presentation"
        )
        v_layout.addWidget(selected_strip)

        self._compact_buttons = (
            self.btnQuickAdd,
            self.btnCreateCharacter,
            self.btnRollInit,
            self.btnSortInit,
            self.btnCombatMore,
            self.btnEdit,
            self.btnStatuses,
            self.btnMakeCurrent,
            self.btnSelectedMore,
        )
        for button in self._compact_buttons:
            button.setProperty("combatCompact", True)
            button.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Minimum,
                QtWidgets.QSizePolicy.Policy.Fixed,
            )
        self._sync_compact_button_widths()

    def _sync_compact_button_widths(self):
        for button in getattr(self, "_compact_buttons", ()):
            padding = 30 if button.menu() is not None else 18
            button.setMinimumWidth(
                max(36, button.fontMetrics().horizontalAdvance(button.text()) + padding)
            )

    def showEvent(self, event):
        self._sync_compact_button_widths()
        super().showEvent(event)

    def changeEvent(self, event):
        if event.type() in {
            QtCore.QEvent.Type.FontChange,
            QtCore.QEvent.Type.StyleChange,
            QtCore.QEvent.Type.PaletteChange,
        }:
            self._sync_compact_button_widths()
        super().changeEvent(event)

    def _wire_signals(self):
        self.btnEdit.clicked.connect(self._edit_selected)
        self.btnStatuses.clicked.connect(self._edit_statuses_selected)
        self.btnMakeCurrent.clicked.connect(self._make_selected_current)
        self.listCombat.itemSelectionChanged.connect(self._on_combat_selection_changed)
        self.listCombat.customContextMenuRequested.connect(self._open_combat_context_menu)
        self.listCombat.viewportResized.connect(self._resize_combat_rows)
        self.btnRollInit.clicked.connect(self._roll_initiative_all)
        self.btnSortInit.clicked.connect(self._sort_by_initiative)
        self._delete_shortcut = QtGui.QShortcut(
            QtGui.QKeySequence(QtCore.Qt.Key.Key_Delete),
            self.listCombat,
        )
        self._delete_shortcut.setContext(QtCore.Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._delete_shortcut.activated.connect(self._remove_selected)
        self._edit_shortcut = QtGui.QShortcut(
            QtGui.QKeySequence(QtCore.Qt.Key.Key_Return),
            self.listCombat,
        )
        self._edit_shortcut.setContext(QtCore.Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._edit_shortcut.activated.connect(self._edit_selected)
        self._edit_enter_shortcut = QtGui.QShortcut(
            QtGui.QKeySequence(QtCore.Qt.Key.Key_Enter),
            self.listCombat,
        )
        self._edit_enter_shortcut.setContext(
            QtCore.Qt.ShortcutContext.WidgetWithChildrenShortcut
        )
        self._edit_enter_shortcut.activated.connect(self._edit_selected)

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
        ensure_live_combat_instance_ids(self.combatants)
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
            ensure_live_combat_instance_ids(self.combatants)
            self._refresh_combat_list()
            self._persist_party()
            self.parent._log(f"Created character: {payload['name']}")

    def _open_rosters_module(self):
        dock = getattr(self.parent, "_dock_rosters", None)
        if dock is not None:
            dock.show()
            dock.raise_()
        roster_tab = getattr(self.parent, "rosters_tab", None)
        search = getattr(roster_tab, "edSearch", None)
        if search is not None:
            search.setFocus()

    def _edit_selected(self):
        rows = self.listCombat.selectedIndexes()
        if not rows: return
        CombatTab._edit_combatant(self, rows[0].row())

    def _edit_combatant(self, idx: int):
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

    def _set_current_turn(self, idx: int):
        if not (0 <= idx < len(self.combatants)):
            return
        self.turn_index = idx
        self._refresh_combat_list()
        self._persist_party()
        self.parent._log(f"Current turn set to: {self.combatants[idx].get('name', '?')}")

    def _make_selected_current(self):
        rows = self.listCombat.selectedIndexes()
        if rows:
            self._set_current_turn(rows[0].row())

    def _open_combat_context_menu(self, position: QtCore.QPoint):
        item = self.listCombat.itemAt(position)
        if item is None:
            return
        self._show_combatant_menu(
            self.listCombat.row(item),
            self.listCombat.viewport().mapToGlobal(position),
        )

    def _show_combatant_menu(self, idx: int, global_position: QtCore.QPoint):
        if not (0 <= idx < len(self.combatants)):
            return
        item = self.listCombat.item(idx)
        if item is not None and not item.isSelected():
            self.listCombat.clearSelection()
            item.setSelected(True)
            self.listCombat.setCurrentItem(item)
        menu = QtWidgets.QMenu(self)
        edit = menu.addAction("Edit")
        current = menu.addAction("Make Current")
        statuses = menu.addAction("Manage Conditions…")
        adjust = menu.addMenu("Adjust Primary Metric")
        adjust_actions = {}
        for label, delta in (
            ("Damage 5", -5),
            ("Damage 1", -1),
            ("Heal 1", 1),
            ("Heal 5", 5),
        ):
            adjust_actions[adjust.addAction(label)] = delta
        set_metric = adjust.addAction("Set Current Value…")
        duplicate = menu.addAction("Duplicate")
        menu.addSeparator()
        remove = menu.addAction("Remove")
        chosen = menu.exec(global_position)
        if chosen == edit:
            self._edit_combatant(idx)
        elif chosen == current:
            self._set_current_turn(idx)
        elif chosen == statuses:
            self._edit_statuses_selected()
        elif chosen in adjust_actions:
            self._adjust_combatant(idx, adjust_actions[chosen])
        elif chosen == set_metric:
            self._set_selected_metric()
        elif chosen == duplicate:
            self._duplicate_selected()
        elif chosen == remove:
            self._remove_selected()
    
    def _remove_selected(self):
        rows = sorted([i.row() for i in self.listCombat.selectedIndexes()], reverse=True)
        if not rows: return
        current_id = (
            self.combatants[self.turn_index].get(COMBAT_INSTANCE_ID_FIELD)
            if 0 <= self.turn_index < len(self.combatants)
            else None
        )
        previous_index = self.turn_index
        removed_names = []
        for r in rows:
            if 0 <= r < len(self.combatants):
                removed_names.append(self.combatants.pop(r)["name"])
        
        self.turn_index = live_combatant_index(self.combatants, current_id)
        if self.turn_index < 0 and self.combatants and previous_index >= 0:
            self.turn_index = min(previous_index, len(self.combatants) - 1)
            
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
                new_item.pop(COMBAT_INSTANCE_ID_FIELD, None)
                
                all_names = [m.get("name") for m in self.combatants]
                base_name = original.get("name").split(" (")[0]
                suffixes = collect_suffixes(base_name, all_names)
                suffix = next_suffix(suffixes)
                
                new_item["name"] = f"{base_name} ({suffix})"
                new_items.append(new_item)
        
        self.combatants.extend(new_items)
        ensure_live_combat_instance_ids(self.combatants)
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
        self._warn_metric_conflicts()
        selected_entities = {
            id(self.combatants[index.row()])
            for index in self.listCombat.selectedIndexes()
            if 0 <= index.row() < len(self.combatants)
        }
        selected_rows = {
            index.row() for index in self.listCombat.selectedIndexes()
        }
        current_row = self.listCombat.currentRow()
        scroll_position = self.listCombat.verticalScrollBar().value()
        while self.listCombat.count() > len(self.combatants):
            self.listCombat.takeItem(self.listCombat.count() - 1)
        for i, m in enumerate(self.combatants):
            self._update_combat_row(i)
        self.listCombat.clearSelection()
        restored_identity = False
        for i, entity in enumerate(self.combatants):
            if id(entity) in selected_entities:
                self.listCombat.item(i).setSelected(True)
                restored_identity = True
        if not restored_identity:
            for row in selected_rows:
                if 0 <= row < self.listCombat.count():
                    self.listCombat.item(row).setSelected(True)
        if 0 <= current_row < self.listCombat.count():
            self.listCombat.setCurrentRow(
                current_row,
                QtCore.QItemSelectionModel.SelectionFlag.NoUpdate,
            )
        self.listCombat.verticalScrollBar().setValue(scroll_position)
        self.listCombat.viewport().update()
        self._update_combat_hud()
        self._sync_selected_strip()

    def _combatant_portrait(self, entity: Dict) -> QtGui.QPixmap | None:
        portrait_signature = json.dumps(
            {
                "portrait": entity.get("portrait"),
                "portraits": entity.get("portraits"),
                "source": entity.get(PORTRAIT_SOURCE_DIR_FIELD),
            },
            sort_keys=True,
            default=str,
        )
        if portrait_signature not in self._combat_portrait_cache:
            _entry, pixmap, _path = resolve_entity_portrait(entity)
            self._combat_portrait_cache[portrait_signature] = pixmap
        return self._combat_portrait_cache[portrait_signature]

    def _resize_combat_rows(self):
        width = self.listCombat.viewport().width()
        for row in range(self.listCombat.count()):
            item = self.listCombat.item(row)
            entity = item.data(COMBAT_ENTITY_ROLE) or {}
            secondary = resolve_secondary_combat_metric(entity)
            has_secondary = bool(secondary and secondary.field in entity)
            item.setSizeHint(QtCore.QSize(0, combat_row_height(width, has_secondary)))
        self.listCombat.doItemsLayout()

    def _update_combat_row(self, i: int):
        if not (0 <= i < len(self.combatants)): return
        m = self.combatants[i]
        metric = resolve_combat_metric(m)
        current, maximum = metric_values(m, metric)
        statuses = [str(status) for status in (m.get("statuses") or []) if str(status)]
        secondary = resolve_secondary_combat_metric(m)
        has_secondary = bool(secondary and secondary.field in m)
        accessible_parts = [
            f"{i + 1}. {m.get('name', 'Unnamed combatant')}",
            "Current turn" if i == self.turn_index else "",
            f"Side {m.get('side', 'Enemy')}",
            f"Initiative {m.get('initTotal', '—')}",
            f"{metric.label} {current} of {maximum}",
        ]
        if has_secondary:
            secondary_current, secondary_maximum = metric_values(m, secondary)
            accessible_parts.append(
                f"{secondary.label} {secondary_current} of {secondary_maximum}"
            )
        if statuses:
            accessible_parts.append("Conditions " + ", ".join(statuses))
        accessible_text = ". ".join(part for part in accessible_parts if part)

        if i < self.listCombat.count():
            item = self.listCombat.item(i)
        else:
            item = QtWidgets.QListWidgetItem()
            self.listCombat.addItem(item)

        item.setText(accessible_text)
        item.setData(QtCore.Qt.ItemDataRole.AccessibleTextRole, accessible_text)
        item.setData(COMBAT_ENTITY_ROLE, m)
        item.setData(COMBAT_ACTIVE_ROLE, i == self.turn_index)
        item.setData(COMBAT_ROW_INDEX_ROLE, i)
        item.setData(COMBAT_PORTRAIT_ROLE, self._combatant_portrait(m))
        item.setToolTip(accessible_text)
        item.setSizeHint(
            QtCore.QSize(
                0,
                combat_row_height(self.listCombat.viewport().width(), has_secondary),
            )
        )

    def _update_combat_hud(self):
        self.progressionChanged.emit()

    def _persist_party(self):
        ensure_live_combat_instance_ids(self.combatants)
        current = load_json(PARTY_FP)
        current_document = None
        if current.valid:
            try:
                current_document, _, _, _ = parse_party_document(current.data)
            except ValueError:
                self._party_write_blocked = True
        elif not current.missing:
            self._party_write_blocked = True
        if self._party_write_blocked:
            if not self._party_write_warning_shown:
                self.parent._toast(
                    f"Combat changes are not being saved because {PARTY_FP.name} could not be loaded safely."
                )
                self._party_write_warning_shown = True
            return False
        document = dict(current_document or self._party_document)
        document.update({
            "party": self.combatants,
            "turn_index": self.turn_index,
            "round": self.round,
        })
        write_json(PARTY_FP, document)
        self._party_document = dict(document)
        # Auto-save to session roster whenever party changes
        if self.combatants:
            session_result = load_json(SESSION_ROSTER_FP)
            if session_result.valid and isinstance(session_result.data, dict):
                session_document = dict(session_result.data)
            elif session_result.missing:
                session_document = {}
            else:
                self.parent._toast(
                    f"Session roster not saved because {SESSION_ROSTER_FP.name} is invalid."
                )
                return True
            session_document.update({
                "roster": self.combatants,
                "turn_index": self.turn_index,
                "round": self.round,
            })
            write_json(SESSION_ROSTER_FP, session_document)
        return True
        
    def _load_party(self):
        result = load_json(PARTY_FP)
        if result.missing:
            self.combatants = []
            self.turn_index = -1
            self.round = 1
            self._party_document = {}
        elif result.valid:
            try:
                document, combatants, turn_index, round_number = parse_party_document(result.data)
            except ValueError as e:
                self._party_write_blocked = True
                self.parent._log(f"Party file was not loaded: {e}")
            else:
                self._party_document = document
                self.combatants = combatants
                self.turn_index = turn_index
                self.round = round_number
                ensure_live_combat_instance_ids(self.combatants)
        else:
            self._party_write_blocked = True
            self.parent._log(f"Party file was not loaded: {result.error}")
        
        self._refresh_combat_list()
        if not self._party_write_blocked:
            self.parent._log("Combatants loaded from file.")
        
    def _advance_combat_next(self):
        if not self.combatants: return
        self.round = max(1, self.round)
        if self.turn_index < 0:
            self.turn_index = 0
        elif self.turn_index == len(self.combatants) - 1:
            self.turn_index = 0
            self.round += 1
        else:
            self.turn_index += 1
            
        self._refresh_combat_list()
        self._persist_party()

    def _advance_combat_prev(self):
        if not self.combatants: return
        self.round = max(1, self.round)
        if self.turn_index < 0:
            return
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
            self.combatants = [deepcopy(member) for member in members if isinstance(member, dict)]
            ensure_live_combat_instance_ids(self.combatants)
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
        ensure_live_combat_instance_ids(self.combatants)
        write_json(SESSION_ROSTER_FP, {
            "roster": self.combatants,
            "turn_index": self.turn_index,
            "round": self.round,
        })
        self.parent._log(f"Saved session roster ({len(self.combatants)} members)")
            
    def _on_combat_selection_changed(self):
        self._sync_selected_strip()

    def _sync_selected_strip(self):
        if not hasattr(self, "lblSelectedCombatant"):
            return
        rows = sorted({index.row() for index in self.listCombat.selectedIndexes()})
        valid = [row for row in rows if 0 <= row < len(self.combatants)]
        single = len(valid) == 1
        if single:
            entity = self.combatants[valid[0]]
            metric = resolve_combat_metric(entity)
            current, maximum = metric_values(entity, metric)
            text = (
                f"Selected: {entity.get('name', 'Unnamed combatant')} · "
                f"{metric.label} {current}/{maximum}"
            )
        elif valid:
            text = f"Selected: {len(valid)} combatants · Mixed metrics"
        else:
            text = "Selected: none"
        self.lblSelectedCombatant.setText(text)
        self.lblSelectedCombatant.setToolTip(text)
        self.lblSelectedCombatant.setAccessibleName(text)
        self.btnEdit.setEnabled(single)
        self.btnStatuses.setEnabled(single)
        self.btnMakeCurrent.setEnabled(single)
        self.btnSelectedMore.setEnabled(bool(valid))

    def _warn_metric_conflicts(self):
        if not hasattr(self, "_metric_conflict_warnings"):
            self._metric_conflict_warnings = set()
        for idx, m in enumerate(self.combatants):
            metric = resolve_combat_metric(m)
            warning = metric_conflict_warning(m, metric)
            if not warning:
                continue
            key = (idx, m.get("id"), m.get("name"), warning)
            if key in self._metric_conflict_warnings:
                continue
            self._metric_conflict_warnings.add(key)
            if hasattr(self.parent, "_log"):
                self.parent._log(warning)

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
        ensure_live_combat_instance_ids(self.combatants)
        current_id = (
            self.combatants[self.turn_index].get(COMBAT_INSTANCE_ID_FIELD)
            if 0 <= self.turn_index < len(self.combatants)
            else None
        )
        self.combatants.sort(
            key=lambda m: (m.get("initTotal") is None, -(m.get("initTotal") or 0), m.get("name","").lower())
        )
        self.turn_index = live_combatant_index(self.combatants, current_id)
        if current_id is None:
            self.turn_index = -1
        self._refresh_combat_list()
        self._persist_party()
        self.parent._log("Sorted by initiative.")

    def _adjust_hp_selected(self, delta: int):
        rows = [i.row() for i in self.listCombat.selectedIndexes()]
        if not rows: return
        changed = []
        for r in rows:
            changed_label = CombatTab._adjust_combatant_value(self, r, delta)
            if changed_label:
                changed.append(changed_label)
        self._refresh_combat_list()
        self._persist_party()
        if changed:
            self.parent._log(f"Adjusted combat metric for: {', '.join(changed)} ({delta:+})")

    def _adjust_combatant_value(self, row: int, delta: int) -> str | None:
        if not (0 <= row < len(self.combatants)):
            return None
        entity = self.combatants[row]
        metric = resolve_combat_metric(entity)
        current = coerce_metric_int(entity.get(metric.field), 0)
        maximum = entity.get(metric.max_field)
        if maximum is None:
            maximum = current if current > 0 else 1
        maximum = max(1, coerce_metric_int(maximum, 1))
        entity[metric.field] = max(0, min(current + delta, maximum))
        return f"{entity.get('name', '?')} {metric.label}"

    def _adjust_combatant(self, row: int, delta: int):
        changed = self._adjust_combatant_value(row, delta)
        if not changed:
            return
        self._refresh_combat_list()
        self._persist_party()
        self.parent._log(f"Adjusted combat metric for: {changed} ({delta:+})")

    def _set_selected_metric(self):
        rows = self.listCombat.selectedIndexes()
        if len(rows) != 1:
            return
        row = rows[0].row()
        if not (0 <= row < len(self.combatants)):
            return
        entity = self.combatants[row]
        metric = resolve_combat_metric(entity)
        current, maximum = metric_values(entity, metric)
        value, accepted = QtWidgets.QInputDialog.getInt(
            self,
            f"Set {metric.label}",
            f"{entity.get('name', 'Combatant')} — {metric.label}:",
            current,
            0,
            max(1, maximum),
        )
        if not accepted:
            return
        entity[metric.field] = value
        self._refresh_combat_list()
        self._persist_party()
        self.parent._log(
            f"Set {entity.get('name', '?')} {metric.label} to {value}."
        )

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
