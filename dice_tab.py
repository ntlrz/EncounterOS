# dice_tab.py — Dice roller with formula (e.g. 1d20+5) and session roll log.

from __future__ import annotations
from datetime import datetime
from PySide6 import QtWidgets, QtCore, QtGui
from typing import List, Dict, Any

from app_paths import DICE_SESSION_FP, LOG_DIR
from helpers import load_json, roll_dice, now_iso, write_json

LOG_DIR.mkdir(parents=True, exist_ok=True)


def _load_session_rolls() -> List[Dict[str, Any]]:
    result = load_json(DICE_SESSION_FP)
    if not result.valid or not isinstance(result.data, dict):
        return []
    rolls = result.data.get("rolls")
    return list(rolls) if isinstance(rolls, list) else []


def _save_session_rolls(rolls: List[Dict[str, Any]], document: Dict[str, Any] | None = None) -> Dict[str, Any]:
    DICE_SESSION_FP.parent.mkdir(parents=True, exist_ok=True)
    output = dict(document or {})
    output["rolls"] = rolls
    write_json(DICE_SESSION_FP, output)
    return output


def format_roll_timestamp(value: Any) -> str:
    """Format a stored ISO timestamp for compact display without rewriting it."""
    if not isinstance(value, str) or not value.strip():
        return ""
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        local = parsed.astimezone()
        hour = local.hour % 12 or 12
        suffix = "AM" if local.hour < 12 else "PM"
        return f"{hour}:{local.minute:02d} {suffix}"
    except (TypeError, ValueError, OSError):
        return text.split(".", 1)[0].replace("T", " ")


def invalid_roll_message(breakdown: Any) -> str | None:
    text = str(breakdown or "").strip()
    return text if text.lower().startswith("invalid formula") else None


def soft_wrap_display(value: Any, token_span: int = 24) -> str:
    """Add invisible wrap opportunities without changing persisted content."""
    text = str(value or "")
    output = []
    span = 0
    for character in text:
        output.append(character)
        span += 1
        if character.isspace():
            span = 0
        elif character in {"+", ",", "=", "→"} or span >= token_span:
            output.append("\u200b")
            span = 0
    return "".join(output)


class DiceTab(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QMainWindow):
        super().__init__()
        self.parent = parent
        self._rolls: List[Dict[str, Any]] = []
        self._session_document: Dict[str, Any] = {}
        self._session_write_blocked = False
        self._build_ui()
        self._load_session()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(12)

        # Primary control row
        controls = QtWidgets.QHBoxLayout()
        formula_label = QtWidgets.QLabel("Formula")
        self.formula_edit = QtWidgets.QLineEdit()
        self.formula_edit.setPlaceholderText("e.g. 1d20+5, 2d6, d20")
        self.formula_edit.setAccessibleName("Dice formula")
        self.formula_edit.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Fixed,
        )
        self.formula_edit.returnPressed.connect(self._do_roll)
        self.roll_btn = QtWidgets.QPushButton("Roll")
        self.roll_btn.setProperty("class", "primary")
        self.roll_btn.setAccessibleName("Roll dice")
        self.roll_btn.clicked.connect(self._do_roll)
        controls.addWidget(formula_label)
        controls.addWidget(self.formula_edit, 1)
        controls.addWidget(self.roll_btn)
        layout.addLayout(controls)

        self.error_label = QtWidgets.QLabel("")
        self.error_label.setObjectName("diceErrorLabel")
        self.error_label.setAccessibleName("Dice formula error")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #d93025; font-weight: 600;")
        self.error_label.hide()
        layout.addWidget(self.error_label)

        # Dedicated current-result area
        self.result_frame = QtWidgets.QFrame()
        self.result_frame.setObjectName("diceResultFrame")
        self.result_frame.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.result_frame.setStyleSheet(
            "QFrame#diceResultFrame {"
            " border: 1px solid rgba(127, 127, 127, 90);"
            " border-radius: 10px;"
            " background-color: rgba(127, 127, 127, 20);"
            "}"
        )
        result_layout = QtWidgets.QVBoxLayout(self.result_frame)
        result_layout.setContentsMargins(16, 14, 16, 14)
        result_layout.setSpacing(6)
        self.total_label = QtWidgets.QLabel("—")
        total_font = self.total_label.font()
        total_font.setPointSize(34)
        total_font.setBold(True)
        self.total_label.setFont(total_font)
        self.total_label.setAlignment(QtCore.Qt.AlignCenter)
        self.total_label.setAccessibleName("Latest dice total")
        self.total_label.setMinimumHeight(
            QtGui.QFontMetrics(total_font).height() + 8
        )
        self.total_label.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Minimum,
        )
        self.breakdown_label = QtWidgets.QLabel("Roll breakdown will appear here.")
        self.breakdown_label.setAlignment(QtCore.Qt.AlignCenter)
        self.breakdown_label.setWordWrap(True)
        self.breakdown_label.setTextInteractionFlags(
            QtCore.Qt.TextSelectableByMouse
        )
        self.breakdown_label.setAccessibleName("Latest dice breakdown")
        result_layout.addWidget(self.total_label)
        result_layout.addWidget(self.breakdown_label)
        layout.addWidget(self.result_frame)

        self._result_effect = QtWidgets.QGraphicsOpacityEffect(self.result_frame)
        self._result_effect.setOpacity(1.0)
        self.result_frame.setGraphicsEffect(self._result_effect)
        self._result_animation = QtCore.QPropertyAnimation(
            self._result_effect, b"opacity", self
        )
        self._result_animation.setDuration(150)
        self._result_animation.setStartValue(0.90)
        self._result_animation.setEndValue(1.0)
        self._result_animation.setEasingCurve(QtCore.QEasingCurve.OutCubic)

        # Compact persistent history
        history_header = QtWidgets.QHBoxLayout()
        history_title = QtWidgets.QLabel("Session History")
        history_font = history_title.font()
        history_font.setBold(True)
        history_title.setFont(history_font)
        self.clear_btn = QtWidgets.QPushButton("Clear History")
        self.clear_btn.clicked.connect(self._clear_session)
        history_header.addWidget(history_title)
        history_header.addStretch(1)
        history_header.addWidget(self.clear_btn)
        layout.addLayout(history_header)
        self.log_list = QtWidgets.QListWidget()
        self.log_list.setAlternatingRowColors(True)
        self.log_list.setWordWrap(True)
        self.log_list.setAccessibleName("Dice session history")
        self.log_list.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Expanding,
        )
        layout.addWidget(self.log_list, 1)

        # Compatibility alias for older callers that inspected the old label.
        self.result_label = self.breakdown_label

    def _load_session(self):
        result = load_json(DICE_SESSION_FP)
        if result.missing:
            self._session_document = {}
            self._rolls = []
        elif result.valid and isinstance(result.data, dict) and isinstance(result.data.get("rolls", []), list):
            self._session_document = dict(result.data)
            self._rolls = list(result.data.get("rolls", []))
        else:
            self._session_document = {}
            self._rolls = []
            self._session_write_blocked = True
            if hasattr(self.parent, "_log"):
                self.parent._log(f"Dice session was not loaded safely: {DICE_SESSION_FP.name}")
        self._refresh_log()
        latest = next(
            (roll for roll in reversed(self._rolls) if isinstance(roll, dict)),
            None,
        )
        if latest is not None:
            self._show_latest(latest, animate=False)

    def _persist_session(self) -> bool:
        if self._session_write_blocked:
            if hasattr(self.parent, "_toast"):
                self.parent._toast(
                    f"Dice history not saved because {DICE_SESSION_FP.name} is invalid."
                )
            return False
        current = load_json(DICE_SESSION_FP)
        if current.valid and isinstance(current.data, dict):
            document = dict(current.data)
        elif current.missing:
            document = dict(self._session_document)
        else:
            self._session_write_blocked = True
            if hasattr(self.parent, "_toast"):
                self.parent._toast(
                    f"Dice history not saved because {DICE_SESSION_FP.name} is invalid."
                )
            return False
        self._session_document = _save_session_rolls(self._rolls, document)
        return True

    def _refresh_log(self):
        self.log_list.clear()
        for r in reversed(self._rolls):
            if not isinstance(r, dict):
                item = QtWidgets.QListWidgetItem("Unavailable history entry")
                item.setData(QtCore.Qt.UserRole, r)
                self.log_list.addItem(item)
                continue
            formula = r.get("formula", "?")
            result = r.get("result", "?")
            breakdown = str(r.get("breakdown") or "")
            timestamp = format_roll_timestamp(r.get("timestamp"))
            first_line = f"{timestamp}   {formula}  →  {result}".strip()
            item = QtWidgets.QListWidgetItem(
                f"{first_line}\n{breakdown}"
            )
            item.setToolTip(breakdown)
            item.setData(QtCore.Qt.UserRole, dict(r))
            item.setSizeHint(
                QtCore.QSize(
                    0,
                    self.log_list.fontMetrics().lineSpacing() * 2 + 12,
                )
            )
            self.log_list.addItem(item)
        if self.log_list.count():
            self.log_list.setCurrentRow(0)
            self.log_list.scrollToItem(self.log_list.item(0))

    def _show_latest(self, entry: Dict[str, Any], animate: bool = True):
        self.total_label.setText(str(entry.get("result", "—")))
        self.breakdown_label.setText(
            soft_wrap_display(
                entry.get("breakdown") or "No breakdown available."
            )
        )
        if animate:
            self._result_animation.stop()
            self._result_effect.setOpacity(0.90)
            self._result_animation.start()

    def _do_roll(self):
        formula = self.formula_edit.text().strip() or "1d20"
        total, breakdown = roll_dice(formula)
        invalid = invalid_roll_message(breakdown)
        if invalid:
            self.error_label.setText(soft_wrap_display(invalid))
            self.error_label.show()
            self.formula_edit.setFocus()
            return
        if not breakdown:
            self.error_label.setText(
                soft_wrap_display(f"Invalid formula: {formula}")
            )
            self.error_label.show()
            self.formula_edit.setFocus()
            return
        self.error_label.clear()
        self.error_label.hide()
        entry = {
            "formula": formula,
            "result": total,
            "breakdown": breakdown,
            "timestamp": now_iso(),
        }
        self._rolls.append(entry)
        self._persist_session()
        self._show_latest(entry)
        self._refresh_log()
        self.formula_edit.setFocus()
        if hasattr(self.parent, "_log"):
            self.parent._log(f"Dice: {breakdown}")

    def _clear_session(self):
        self._rolls = []
        self._persist_session()
        self._refresh_log()
        if hasattr(self.parent, "_log"):
            self.parent._log("Dice session log cleared.")
