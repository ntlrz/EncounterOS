from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from PySide6 import QtCore, QtGui, QtWidgets

from app_paths import APP_DIR, DIALOG_PORTRAITS_DIR


PORTRAIT_SOURCE_DIR_FIELD = "_portrait_source_dir"
IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.webp)"


def _new_portrait_id(used: set[str]) -> str:
    while True:
        candidate = str(uuid4())
        if candidate not in used:
            return candidate


def normalized_portraits(entity: Any, include_legacy: bool = True) -> list[dict]:
    """Return an editable deep copy without mutating or rewriting the source."""
    entity = entity if isinstance(entity, dict) else {}
    source = entity.get("portraits")
    raw_entries = source if isinstance(source, list) else []
    entries: list[dict] = []
    used: set[str] = set()
    for index, raw in enumerate(raw_entries):
        if not isinstance(raw, dict):
            continue
        entry = deepcopy(raw)
        portrait_id = entry.get("id")
        if (
            not isinstance(portrait_id, str)
            or not portrait_id.strip()
            or portrait_id.strip() in used
        ):
            portrait_id = _new_portrait_id(used)
        else:
            portrait_id = portrait_id.strip()
        used.add(portrait_id)
        file_value = entry.get("file")
        if not isinstance(file_value, str):
            file_value = ""
        label = entry.get("label")
        if not isinstance(label, str) or not label.strip():
            label = Path(file_value).stem if file_value else f"Portrait {index + 1}"
        entry.update({
            "id": portrait_id,
            "label": label.strip(),
            "file": file_value.strip(),
        })
        entries.append(entry)

    legacy = entity.get("portrait")
    if (
        include_legacy
        and not entries
        and isinstance(legacy, str)
        and legacy.strip()
    ):
        entries.append({
            "id": _new_portrait_id(used),
            "label": "Default",
            "file": legacy.strip(),
        })
    return entries


def portrait_source_dir(entity: Any) -> Path | None:
    if not isinstance(entity, dict):
        return None
    value = entity.get(PORTRAIT_SOURCE_DIR_FIELD)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return Path(value).expanduser()
    except (OSError, ValueError):
        return None


def portable_portrait_path(path: str | Path, source_dir: Path | None) -> str:
    selected = Path(path)
    try:
        selected = selected.resolve()
    except OSError:
        return str(selected)
    for base in (source_dir, APP_DIR):
        if base is None:
            continue
        try:
            return str(selected.relative_to(Path(base).resolve()))
        except (OSError, ValueError):
            continue
    return str(selected)


def portrait_path_candidates(
    file_value: Any,
    source_dir: Path | None = None,
) -> list[Path]:
    if not isinstance(file_value, str) or not file_value.strip():
        return []
    text = file_value.strip()
    raw = Path(text)
    candidates: list[Path] = []
    if raw.is_absolute():
        candidates.append(raw)
    else:
        if source_dir is not None:
            candidates.append(Path(source_dir) / raw)
        candidates.append(APP_DIR / raw)
        candidates.append(DIALOG_PORTRAITS_DIR / raw)
        candidates.append(DIALOG_PORTRAITS_DIR / raw.name)
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def resolve_portrait_path(
    file_value: Any,
    source_dir: Path | None = None,
) -> Path | None:
    for candidate in portrait_path_candidates(file_value, source_dir):
        try:
            if candidate.is_file():
                reader = QtGui.QImageReader(str(candidate))
                if reader.canRead():
                    return candidate
        except (OSError, ValueError):
            continue
    return None


def load_portrait_pixmap(
    file_value: Any,
    source_dir: Path | None = None,
) -> tuple[QtGui.QPixmap | None, Path | None]:
    path = resolve_portrait_path(file_value, source_dir)
    if path is None:
        return None, None
    pixmap = QtGui.QPixmap(str(path))
    if pixmap.isNull():
        return None, path
    return pixmap, path


def resolve_entity_portrait(
    entity: Any,
    portrait_id: str | None = None,
) -> tuple[dict | None, QtGui.QPixmap | None, Path | None]:
    entries = normalized_portraits(entity)
    ordered: list[dict] = []
    if portrait_id:
        selected = next(
            (entry for entry in entries if entry.get("id") == portrait_id),
            None,
        )
        if selected is not None:
            ordered.append(selected)
    ordered.extend(entry for entry in entries if entry not in ordered)
    source_dir = portrait_source_dir(entity)
    for entry in ordered:
        pixmap, path = load_portrait_pixmap(entry.get("file"), source_dir)
        if pixmap is not None:
            return entry, pixmap, path
    return (ordered[0] if ordered else None), None, None


def find_speaker_entity(block: Any, entities: Iterable[dict]) -> dict | None:
    if not isinstance(block, dict):
        return None
    candidates = [entity for entity in entities if isinstance(entity, dict)]
    speaker_id = block.get("speaker_id")
    if isinstance(speaker_id, str) and speaker_id:
        match = next(
            (entity for entity in candidates if entity.get("id") == speaker_id),
            None,
        )
        if match is not None:
            return match
    speaker = str(block.get("speaker") or "").strip().casefold()
    if not speaker:
        return None
    matches = [
        entity
        for entity in candidates
        if str(entity.get("name") or "").strip().casefold() == speaker
    ]
    return matches[0] if len(matches) == 1 else None


def resolve_dialog_portrait(
    block: Any,
    entities: Iterable[dict],
) -> tuple[QtGui.QPixmap | None, Path | None, str]:
    if not isinstance(block, dict):
        return None, None, "none"
    explicit = block.get("portrait")
    if isinstance(explicit, str) and explicit.strip():
        pixmap, path = load_portrait_pixmap(
            explicit,
            portrait_source_dir(block),
        )
        if pixmap is not None:
            return pixmap, path, "custom"
    entity = find_speaker_entity(block, entities)
    if entity is None:
        return None, None, "none"
    portrait_id = block.get("portrait_id")
    selected = portrait_id if isinstance(portrait_id, str) else None
    _entry, pixmap, path = resolve_entity_portrait(entity, selected)
    return pixmap, path, "selected" if selected else "default"


class PortraitLibraryWidget(QtWidgets.QGroupBox):
    changed = QtCore.Signal()

    def __init__(self, entity: dict, parent=None):
        super().__init__("Portraits", parent)
        self.entity = entity if isinstance(entity, dict) else {}
        self.source_dir = portrait_source_dir(self.entity)
        self._portraits = normalized_portraits(self.entity)
        self._build_ui()
        self._refresh()

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        self.preview = QtWidgets.QLabel()
        self.preview.setFixedSize(220, 150)
        self.preview.setAlignment(QtCore.Qt.AlignCenter)
        self.preview.setFrameShape(QtWidgets.QFrame.StyledPanel)
        root.addWidget(self.preview, alignment=QtCore.Qt.AlignHCenter)
        self.summary = QtWidgets.QLabel()
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)
        self.list = QtWidgets.QListWidget()
        self.list.currentRowChanged.connect(self._refresh_preview)
        root.addWidget(self.list)

        buttons = QtWidgets.QGridLayout()
        actions = (
            ("Add…", self._choose_add, 0, 0),
            ("Replace…", self._choose_replace, 0, 1),
            ("Rename…", self._choose_rename, 0, 2),
            ("Remove", self._remove_selected, 1, 0),
            ("Set as Default", self._set_default, 1, 1),
            ("Clear All…", self._confirm_clear, 1, 2),
            ("Move Up", lambda: self._move_selected(-1), 2, 0),
            ("Move Down", lambda: self._move_selected(1), 2, 1),
        )
        for label, callback, row, column in actions:
            button = QtWidgets.QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button, row, column)
        root.addLayout(buttons)

    def portraits(self) -> list[dict]:
        return deepcopy(self._portraits)

    def _refresh(self, selected_id: str | None = None):
        current_id = selected_id
        if current_id is None and 0 <= self.list.currentRow() < len(self._portraits):
            current_id = self._portraits[self.list.currentRow()].get("id")
        self.list.clear()
        selected_row = 0
        for index, entry in enumerate(self._portraits):
            prefix = "Default — " if index == 0 else ""
            item = QtWidgets.QListWidgetItem(
                f"{prefix}{entry.get('label')} — {Path(entry.get('file') or '').name or 'No file'}"
            )
            item.setData(QtCore.Qt.UserRole, entry.get("id"))
            self.list.addItem(item)
            if entry.get("id") == current_id:
                selected_row = index
        self.list.setCurrentRow(selected_row if self._portraits else -1)
        self._refresh_preview()
        self.changed.emit()

    def _refresh_preview(self):
        row = self.list.currentRow()
        if not 0 <= row < len(self._portraits):
            self.preview.clear()
            self.preview.setText("No portraits")
            self.summary.setText("No portrait is assigned.")
            return
        entry = self._portraits[row]
        pixmap, path = load_portrait_pixmap(entry.get("file"), self.source_dir)
        default_text = " • Default" if row == 0 else ""
        if pixmap is None:
            self.preview.clear()
            self.preview.setText("Portrait unavailable")
            self.summary.setText(
                f"{entry.get('label')}{default_text}\n{entry.get('file') or 'No file'}"
            )
            return
        self.preview.setPixmap(
            pixmap.scaled(
                self.preview.size(),
                QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.SmoothTransformation,
            )
        )
        self.summary.setText(
            f"{entry.get('label')}{default_text}\n{path}"
        )

    def _choose_image(self, title: str) -> str:
        path, _selected_filter = QtWidgets.QFileDialog.getOpenFileName(
            self,
            title,
            str(self.source_dir or APP_DIR),
            IMAGE_FILTER,
        )
        return path

    def _choose_add(self):
        path = self._choose_image("Add Portrait")
        if path:
            self.add_portrait(path)

    def add_portrait(self, path: str, label: str | None = None):
        used = {str(entry.get("id")) for entry in self._portraits}
        stored_path = portable_portrait_path(path, self.source_dir)
        entry = {
            "id": _new_portrait_id(used),
            "label": (label or Path(path).stem or "Portrait").strip(),
            "file": stored_path,
        }
        self._portraits.append(entry)
        self._refresh(entry["id"])

    def _choose_replace(self):
        path = self._choose_image("Replace Portrait")
        if path:
            self.replace_selected(path)

    def replace_selected(self, path: str):
        row = self.list.currentRow()
        if not 0 <= row < len(self._portraits):
            return
        portrait_id = self._portraits[row]["id"]
        self._portraits[row]["file"] = portable_portrait_path(path, self.source_dir)
        self._refresh(portrait_id)

    def _choose_rename(self):
        row = self.list.currentRow()
        if not 0 <= row < len(self._portraits):
            return
        label, accepted = QtWidgets.QInputDialog.getText(
            self,
            "Portrait Label",
            "Label:",
            text=self._portraits[row].get("label", ""),
        )
        if accepted and label.strip():
            self.rename_selected(label)

    def rename_selected(self, label: str):
        row = self.list.currentRow()
        if not 0 <= row < len(self._portraits) or not label.strip():
            return
        portrait_id = self._portraits[row]["id"]
        self._portraits[row]["label"] = label.strip()
        self._refresh(portrait_id)

    def _remove_selected(self):
        row = self.list.currentRow()
        if 0 <= row < len(self._portraits):
            self._portraits.pop(row)
            self._refresh()

    def _move_selected(self, delta: int):
        row = self.list.currentRow()
        target = row + delta
        if not (0 <= row < len(self._portraits) and 0 <= target < len(self._portraits)):
            return
        portrait_id = self._portraits[row]["id"]
        self._portraits[row], self._portraits[target] = (
            self._portraits[target],
            self._portraits[row],
        )
        self._refresh(portrait_id)

    def _set_default(self):
        row = self.list.currentRow()
        if not 0 < row < len(self._portraits):
            return
        entry = self._portraits.pop(row)
        self._portraits.insert(0, entry)
        self._refresh(entry["id"])

    def _confirm_clear(self):
        if not self._portraits:
            return
        answer = QtWidgets.QMessageBox.question(
            self,
            "Clear Portraits",
            "Remove all portraits from this character?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if answer == QtWidgets.QMessageBox.Yes:
            self.clear_all()

    def clear_all(self):
        self._portraits = []
        self._refresh()


class DialogBlockEditor(QtWidgets.QDialog):
    """Edit dialog content and its constrained portrait presentation fields."""

    def __init__(
        self,
        block: dict,
        entities: Iterable[dict],
        parent=None,
        title: str = "Edit Dialog Block",
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(480)
        self._original = deepcopy(block)
        self._entities = [entity for entity in entities if isinstance(entity, dict)]

        form = QtWidgets.QFormLayout(self)
        self.text = QtWidgets.QPlainTextEdit(str(block.get("text") or ""))
        form.addRow("Dialog Text", self.text)

        self.speaker_source = QtWidgets.QComboBox()
        self.speaker_source.addItem("Existing Character", "linked")
        self.speaker_source.addItem("Ad Hoc / Unlinked", "ad_hoc")
        form.addRow("Speaker source", self.speaker_source)

        self.speaker = QtWidgets.QComboBox()
        self.speaker.addItem("Choose character…", None)
        for entity in self._entities:
            name = str(entity.get("name") or "Unnamed")
            identity = entity.get("id")
            suffix = f" — {identity}" if identity else " — unlinked source"
            self.speaker.addItem(name + suffix, identity)
        self.ad_hoc_speaker = QtWidgets.QLineEdit()
        self.ad_hoc_speaker.setPlaceholderText("Optional speaker; blank for narration")
        speaker_id = block.get("speaker_id")
        speaker_index = self.speaker.findData(speaker_id) if speaker_id else -1
        if speaker_index < 0:
            speaker_name = str(block.get("speaker") or "").strip().casefold()
            name_matches = [
                index + 1
                for index, entity in enumerate(self._entities)
                if str(entity.get("name") or "").strip().casefold() == speaker_name
            ]
            if speaker_name and len(name_matches) == 1:
                speaker_index = name_matches[0]
        if speaker_index >= 0:
            self.speaker.setCurrentIndex(speaker_index)
            self.speaker_source.setCurrentIndex(0)
        else:
            self.speaker_source.setCurrentIndex(1)
            self.ad_hoc_speaker.setText(str(block.get("speaker") or ""))
        self.speaker.currentIndexChanged.connect(self._populate_portraits)
        self.speaker_source.currentIndexChanged.connect(self._speaker_source_changed)
        self.ad_hoc_speaker.textChanged.connect(self._populate_portraits)
        form.addRow("Character", self.speaker)
        form.addRow("Display name", self.ad_hoc_speaker)

        self.portrait = QtWidgets.QComboBox()
        self.portrait.currentIndexChanged.connect(self._refresh_preview)
        form.addRow("Portrait", self.portrait)
        portrait_actions = QtWidgets.QHBoxLayout()
        self.choose_custom_portrait = QtWidgets.QPushButton("Choose Custom Image…")
        self.use_speaker_library = QtWidgets.QPushButton(
            "Use Speaker Portrait Library"
        )
        self.choose_custom_portrait.clicked.connect(self._choose_custom_portrait)
        self.use_speaker_library.clicked.connect(self._use_speaker_library)
        portrait_actions.addWidget(self.choose_custom_portrait)
        portrait_actions.addWidget(self.use_speaker_library)
        form.addRow(portrait_actions)

        self.preview = QtWidgets.QLabel()
        self.preview.setFixedSize(240, 160)
        self.preview.setAlignment(QtCore.Qt.AlignCenter)
        self.preview.setFrameShape(QtWidgets.QFrame.StyledPanel)
        form.addRow("Preview", self.preview)

        self.placement = QtWidgets.QComboBox()
        self.placement.addItems(["left", "center", "right"])
        self.placement.setCurrentText(str(block.get("placement") or "left").lower())
        form.addRow("Placement", self.placement)
        self.facing = QtWidgets.QComboBox()
        self.facing.addItems(["right", "left"])
        self.facing.setCurrentText(
            str(block.get("portrait_facing") or block.get("facing") or "right").lower()
        )
        form.addRow("Facing", self.facing)
        self.scale = QtWidgets.QDoubleSpinBox()
        self.scale.setRange(0.1, 5.0)
        self.scale.setSingleStep(0.1)
        try:
            self.scale.setValue(float(block.get("portrait_scale", 1.0)))
        except (TypeError, ValueError):
            self.scale.setValue(1.0)
        form.addRow("Scale", self.scale)
        self.offset_x = QtWidgets.QSpinBox()
        self.offset_x.setRange(-4096, 4096)
        self.offset_x.setValue(self._safe_int(block.get("portrait_offset_x")))
        form.addRow("Horizontal offset", self.offset_x)
        self.offset_y = QtWidgets.QSpinBox()
        self.offset_y.setRange(-4096, 4096)
        self.offset_y.setValue(self._safe_int(block.get("portrait_offset_y")))
        form.addRow("Vertical offset", self.offset_y)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.accept_shortcut = QtGui.QShortcut(
            QtGui.QKeySequence("Ctrl+Return"), self, activated=self.accept
        )
        self._speaker_source_changed()
        self._populate_portraits()

    @staticmethod
    def _safe_int(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def _speaker_entity(self) -> dict | None:
        if self.speaker_source.currentData() != "linked":
            return None
        index = self.speaker.currentIndex() - 1
        return self._entities[index] if 0 <= index < len(self._entities) else None

    def _speaker_name(self) -> str:
        entity = self._speaker_entity()
        if entity is not None:
            return str(entity.get("name") or "").strip()
        return self.ad_hoc_speaker.text().strip()

    def _speaker_source_changed(self):
        linked = self.speaker_source.currentData() == "linked"
        self.speaker.setEnabled(linked)
        self.ad_hoc_speaker.setEnabled(not linked)
        self._populate_portraits()

    def _populate_portraits(self):
        selected = self.portrait.currentData() if self.portrait.count() else None
        if selected is None:
            selected = self._original.get("portrait_id")
        explicit = self._original.get("portrait")
        self.portrait.blockSignals(True)
        self.portrait.clear()
        if isinstance(explicit, str) and explicit.strip():
            self.portrait.addItem(
                f"Custom image — {Path(explicit).name}", ("custom", explicit)
            )
        self.portrait.addItem("Use Default", ("default", None))
        entity = self._speaker_entity()
        if entity is not None:
            for index, entry in enumerate(normalized_portraits(entity)):
                label = str(entry.get("label") or f"Portrait {index + 1}")
                if index == 0:
                    label = f"{label} (Default)"
                self.portrait.addItem(label, ("portrait", entry.get("id")))
        target = -1
        for index in range(self.portrait.count()):
            kind, value = self.portrait.itemData(index)
            if selected == value or selected == (kind, value):
                target = index
                break
        if target < 0:
            target = 0 if isinstance(explicit, str) and explicit.strip() else (
                self.portrait.findData(("default", None))
            )
        self.portrait.setCurrentIndex(max(0, target))
        self.portrait.blockSignals(False)
        current = self.portrait.currentData()
        self.use_speaker_library.setVisible(
            bool(current and current[0] == "custom")
        )
        self._refresh_preview()

    def select_portrait_id(self, portrait_id: str | None):
        target = ("default", None) if portrait_id is None else (
            "portrait", portrait_id
        )
        for index in range(self.portrait.count()):
            if self.portrait.itemData(index) == target:
                self.portrait.setCurrentIndex(index)
                return

    def _preview_block(self) -> dict:
        block = deepcopy(self._original)
        block["speaker"] = self._speaker_name()
        entity = self._speaker_entity()
        speaker_id = entity.get("id") if entity is not None else None
        if speaker_id:
            block["speaker_id"] = speaker_id
        selection = self.portrait.currentData()
        if selection:
            kind, value = selection
            if kind != "custom":
                block.pop("portrait", None)
            if kind == "portrait":
                block["portrait_id"] = value
            else:
                block.pop("portrait_id", None)
        return block

    def _choose_custom_portrait(self):
        path, _selected_filter = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Choose Custom Dialog Portrait",
            str(portrait_source_dir(self._original) or APP_DIR),
            IMAGE_FILTER,
        )
        if not path:
            return
        stored = portable_portrait_path(
            path, portrait_source_dir(self._original)
        )
        self._original["portrait"] = stored
        self._populate_portraits()

    def _use_speaker_library(self):
        self._original.pop("portrait", None)
        self._populate_portraits()
        self.select_portrait_id(None)

    def _refresh_preview(self):
        current = self.portrait.currentData()
        self.use_speaker_library.setVisible(
            bool(current and current[0] == "custom")
        )
        pixmap, path, source = resolve_dialog_portrait(
            self._preview_block(), self._entities
        )
        if pixmap is None:
            self.preview.clear()
            self.preview.setText("Portrait unavailable" if source != "none" else "No portrait")
            return
        self.preview.setPixmap(
            pixmap.scaled(
                self.preview.size(),
                QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.SmoothTransformation,
            )
        )
        self.preview.setToolTip(str(path or ""))

    def payload(self) -> dict:
        payload = deepcopy(self._original)
        payload["text"] = self.text.toPlainText().strip()
        payload["speaker"] = self._speaker_name()
        entity = self._speaker_entity()
        speaker_id = entity.get("id") if entity is not None else None
        if speaker_id:
            payload["speaker_id"] = speaker_id
        else:
            payload.pop("speaker_id", None)
        selection = self.portrait.currentData()
        if selection:
            kind, value = selection
            if kind != "custom":
                payload.pop("portrait", None)
            if kind == "portrait":
                payload["portrait_id"] = value
            else:
                payload.pop("portrait_id", None)
        payload["placement"] = self.placement.currentText()
        payload["portrait_facing"] = self.facing.currentText()
        payload["portrait_scale"] = self.scale.value()
        payload["portrait_offset_x"] = self.offset_x.value()
        payload["portrait_offset_y"] = self.offset_y.value()
        return payload
