# tracker_overlay.py — EncounterOS overlay HUD. Reads party/config/dialog + themes and paints HUD.
# Compatible with the GM UI posted (auto-refresh, theme hot-reload, enemy status icons).
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path
import traceback

from PySide6.QtCore import Qt, QTimer, QRect, QSize, QPoint, QElapsedTimer
from PySide6.QtGui import (
    QPainter,
    QColor,
    QBrush,
    QPen,
    QFont,
    QPixmap,
    QGuiApplication,
    QFontMetrics,
    QTransform,
)
from PySide6.QtWidgets import QApplication, QWidget
from app_paths import (
    APP_DIR,
    RESOURCE_DIR,
    PARTY_FP,
    CONFIG_FP,
    DIALOG_FP,
    DIALOG_BLOCKS,
    THEMES_DIR,
    STATUS_DIR,
    DIALOG_PORTRAITS_DIR,
    ROSTERS_DIR,
    OVERLAY_LOG_FILE,
)
from combat_metrics import metric_values, resolve_combat_metric, resolve_secondary_combat_metric
from helpers import config_bool, config_choice
from layout_helpers import status_badge_rows
from overlay_theme import load_overlay_theme, overlay_region_rect
from portrait_library import (
    PORTRAIT_SOURCE_DIR_FIELD,
    resolve_dialog_portrait,
    resolve_entity_portrait,
)

BASE_W, BASE_H = 1280, 720
ICON_SIZE = QSize(64,64)


def dialog_line_reveal(text: str, line_index: int, char_index: int) -> str:
    """Return completed lines plus the currently animating line fragment."""
    lines = str(text or "").split("\n")
    if line_index >= len(lines):
        return str(text or "")
    completed = lines[:max(0, line_index)]
    current = lines[max(0, line_index)][:max(0, char_index)]
    return "\n".join(completed + [current])
STATUS_ICON_SZ = QSize(24,24)
ENEMY_HEALTH_DISCLOSURES = {"hidden", "condition", "full"}


def combat_progression_text(combatants, turn_index, round_number) -> str:
    round_number = max(1, int(round_number or 1))
    if not combatants:
        return f"ROUND {round_number}  •  NEXT: —"
    if 0 <= turn_index < len(combatants):
        next_index = (turn_index + 1) % len(combatants)
        next_round = round_number + 1 if next_index == 0 else round_number
    else:
        next_index = 0
        next_round = round_number
    name = str(combatants[next_index].get("name") or "Unnamed")
    next_label = f"NEXT R{next_round}" if next_round != round_number else "NEXT"
    return f"ROUND {round_number}  •  {next_label}: {name}"


def overlay_runtime_log(message: str, error: BaseException | None = None):
    """Write overlay lifecycle diagnostics without depending on the app CWD."""
    try:
        OVERLAY_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).isoformat()
        detail = f"[{timestamp}] {message}"
        if error is not None:
            detail += f": {type(error).__name__}: {error}"
            formatted = "".join(
                traceback.format_exception(type(error), error, error.__traceback__)
            ).strip()
            if formatted:
                detail += f"\n{formatted}"
        with OVERLAY_LOG_FILE.open("a", encoding="utf-8") as stream:
            stream.write(detail + "\n")
    except Exception:
        # Overlay diagnostics must never make the overlay itself unavailable.
        pass


def overlay_state_paths() -> dict[str, Path]:
    """Return every production overlay input/resource root for diagnostics."""
    return {
        "application": APP_DIR,
        "resources": RESOURCE_DIR,
        "party": PARTY_FP,
        "config": CONFIG_FP,
        "dialog_text": DIALOG_FP,
        "dialog_index": DIALOG_FP.with_suffix(".json"),
        "dialog_blocks": DIALOG_BLOCKS,
        "themes": THEMES_DIR,
        "status_icons": STATUS_DIR,
        "dialog_portraits": DIALOG_PORTRAITS_DIR,
        "rosters": ROSTERS_DIR,
    }


def log_overlay_path_resolution():
    overlay_runtime_log(
        "Overlay state-file resolution "
        f"(frozen={bool(getattr(sys, 'frozen', False))}, "
        f"executable={Path(sys.executable).resolve()}, "
        f"cwd={Path.cwd().resolve()})"
    )
    for name, path in overlay_state_paths().items():
        overlay_runtime_log(
            f"Overlay path {name}={path.resolve()} exists={path.exists()}"
        )


def normalize_enemy_health_disclosure(value) -> str:
    return config_choice(value, ENEMY_HEALTH_DISCLOSURES, "condition")


def combat_density(combatant_count: int) -> dict[str, int]:
    """Return bounded presentation density without changing combat data."""
    if combatant_count <= 2:
        return {
            "padding": 10,
            "gap": 6,
            "portrait_size": 56,
            "font_reduction": 0,
            "condition_rows": 2,
        }
    if combatant_count <= 5:
        return {
            "padding": 8,
            "gap": 5,
            "portrait_size": 48,
            "font_reduction": 1,
            "condition_rows": 2,
        }
    return {
        "padding": 6,
        "gap": 4,
        "portrait_size": 38,
        "font_reduction": 2,
        "condition_rows": 1,
    }


def enemy_health_descriptor(combatant) -> str:
    """Map the resolved primary metric to presentation-only disclosure bands."""
    current, maximum, _label = combatant_metric_display(combatant)
    if current <= 0:
        return "Dead"
    ratio = current / maximum
    if ratio > 0.5:
        return "Healthy"
    if ratio > 0.25:
        return "Bruised"
    return "Bloodied"


def dialog_portrait_geometry(
    panel: QRect,
    pixmap_size: QSize,
    presentation,
) -> tuple[QRect, bool]:
    presentation = presentation if isinstance(presentation, dict) else {}
    placement = str(presentation.get("placement") or "left").strip().lower()
    if placement not in {"left", "center", "right"}:
        placement = "left"
    facing = str(
        presentation.get("portrait_facing")
        or presentation.get("facing")
        or "right"
    ).strip().lower()
    if facing not in {"left", "right"}:
        facing = "right"
    try:
        scale = float(presentation.get("portrait_scale", 1.0))
    except (TypeError, ValueError):
        scale = 1.0
    if not 0.25 <= scale <= 3.0:
        scale = 1.0

    def safe_offset(name):
        value = presentation.get(name, 0)
        if isinstance(value, bool):
            return 0
        try:
            return max(-BASE_W, min(BASE_W, int(value)))
        except (TypeError, ValueError):
            return 0

    offset_x = safe_offset("portrait_offset_x")
    offset_y = safe_offset("portrait_offset_y")
    source_w = max(1, pixmap_size.width())
    source_h = max(1, pixmap_size.height())
    height = round(max(160, min(340, panel.height() * 2.2)) * scale)
    width = max(1, round(height * source_w / source_h))
    if placement == "center":
        x = panel.center().x() - width // 2
    elif placement == "right":
        x = panel.right() - width - 16 + 1
    else:
        x = panel.x() + 16
    bottom = panel.y() + round(panel.height() * 0.62)
    return (
        QRect(x + offset_x, bottom - height + 1 + offset_y, width, height),
        facing == "left",
    )


def combatant_metric_display(combatant):
    metric = resolve_combat_metric(combatant)
    current, maximum = metric_values(combatant, metric)
    return current, maximum, metric.label


def combatant_metric_displays(
    combatant,
    include_secondary: bool = True,
    respect_overlay_visibility: bool = False,
):
    displays = [combatant_metric_display(combatant)]
    secondary = resolve_secondary_combat_metric(combatant)
    if (
        include_secondary
        and secondary
        and secondary.field in combatant
        and (not respect_overlay_visibility or secondary.show_on_overlay)
    ):
        current, maximum = metric_values(combatant, secondary)
        displays.append((current, maximum, secondary.label))
    return displays


def _wrapped_lines(text, max_width, metrics):
    lines = []

    def chunks(word):
        if metrics.horizontalAdvance(word) <= max_width:
            return [word]
        pieces = []
        piece = ""
        for character in word:
            candidate = piece + character
            if piece and metrics.horizontalAdvance(candidate) > max_width:
                pieces.append(piece)
                piece = character
            else:
                piece = candidate
        if piece:
            pieces.append(piece)
        return pieces or [word]

    for explicit_line in str(text or "").split("\n"):
        words = explicit_line.split()
        if not words:
            lines.append("")
            continue
        current = ""
        for word in words:
            for piece in chunks(word):
                candidate = f"{current} {piece}".strip()
                if not current or metrics.horizontalAdvance(candidate) <= max_width:
                    current = candidate
                else:
                    lines.append(current)
                    current = piece
        lines.append(current)
    return lines or [""]


def condition_display_label(renderer_mode: str, label: object) -> str:
    text = str(label)
    return f"[{text}]" if renderer_mode == "rpg_retro" else text


def metric_bar_geometry(renderer_mode: str, rect: QRect, ratio: float):
    ratio = max(0.0, min(float(ratio), 1.0))
    if renderer_mode != "rpg_retro":
        fill_width = round(rect.width() * ratio)
        fill = (
            [QRect(rect.x(), rect.y(), fill_width, rect.height())]
            if fill_width > 0
            else []
        )
        return {"track": [QRect(rect)], "fill": fill}

    segment_count = 10
    segment_gap = 2
    usable = max(segment_count, rect.width() - segment_gap * (segment_count - 1))
    segment_width = max(1, usable // segment_count)
    filled_count = round(segment_count * ratio)
    track = []
    fill = []
    x = rect.x()
    for index in range(segment_count):
        width = (
            rect.right() - x + 1
            if index == segment_count - 1
            else segment_width
        )
        segment = QRect(x, rect.y(), max(1, width), rect.height())
        track.append(segment)
        if index < filled_count:
            fill.append(QRect(segment))
        x += segment_width + segment_gap
    return {"track": track, "fill": fill}

def _compute_fit(src_w, src_h, dst_w, dst_h, mode="contain"):
    sx = dst_w / src_w
    sy = dst_h / src_h
    if mode == "contain":
        s = min(sx, sy)
        return (s, s, (dst_w - src_w * s) / 2.0, (dst_h - src_h * s) / 2.0)
    elif mode == "cover":
        s = max(sx, sy)
        return (s, s, (dst_w - src_w * s) / 2.0, (dst_h - src_h * s) / 2.0)
    elif mode == "stretch":
        return (sx, sy, 0, 0)
    else:
        return (1, 1, 0, 0)

class Overlay(QWidget):
    def __init__(self, theme_name="gm_modern", fit_mode="contain"):
        overlay_runtime_log(
            f"Overlay initialization started theme={theme_name} fit={fit_mode}"
        )
        log_overlay_path_resolution()
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        self.theme_name = theme_name
        self.fit_mode = fit_mode
        self._cfg_screen = None
        self._cfg_fullscreen = True
        self.show_secondary_combat_metrics = False
        self.enemy_health_disclosure = "condition"
        self.theme = self._load_theme()

        self.combatants = []
        self.turn_index = -1
        self.round = 1
        self.dialog = []
        self.dialog_speakers = []
        self.dialog_presentations = []
        self.dialog_portraits = {}
        self.dialog_idx = -1
        self.last_party_mod = 0
        self.last_dialog_mod = 0
        self.last_dialog_blocks_mod = 0
        self.portraits = {}
        self.status_icons = {}
        self.mode = "combat"  # "combat" or "dialog" - controls what overlay shows
        self._transition_from_mode = self.mode
        self._scene_transition_progress = 1.0
        self._scene_transition_elapsed = QElapsedTimer()
        self._scene_transition_timer = QTimer(self)
        self._scene_transition_timer.setInterval(16)
        self._scene_transition_timer.timeout.connect(self._advance_scene_transition)
        # Typing effect for dialog
        self._dialog_typing_text = ""
        self._dialog_typing_index = 0
        self._dialog_typing_line_index = 0
        self._dialog_typing_char_index = 0
        self._dialog_typing_timer = QTimer(self)
        self._dialog_typing_timer.setInterval(30)  # 30ms per character = fast typing
        self._dialog_typing_timer.timeout.connect(self._advance_typing)

        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._update_from_disk)
        self.timer.start()
        
        self.last_cfg_mod = 0

        self._update_from_disk()
        overlay_runtime_log("Overlay initialization completed")

    def set_fit_mode(self, mode: str):
        self.fit_mode = mode
        self.repaint()

    def set_presentation_mode(self, mode: str):
        mode = mode if mode in {"combat", "dialog"} else "combat"
        if mode == self.mode and self._scene_transition_progress >= 1.0:
            return
        self._transition_from_mode = self.mode
        self.mode = mode
        self._scene_transition_progress = 0.0
        self._scene_transition_elapsed.restart()
        self._scene_transition_timer.start()
        if mode == "dialog":
            self._reset_typing_effect()
        self.repaint()

    def _advance_scene_transition(self):
        raw = max(
            0.0,
            min(1.0, self._scene_transition_elapsed.elapsed() / 220.0),
        )
        self._scene_transition_progress = 1.0 - ((1.0 - raw) ** 3)
        if raw >= 1.0:
            self._scene_transition_progress = 1.0
            self._scene_transition_timer.stop()
        self.repaint()

    def move_to_screen(self, screen_name: str | None):
        screens = QGuiApplication.screens()
        target_screen = None
        if screen_name is None:
            target_screen = screens[0]
        else:
            for s in screens:
                if s.name() == screen_name:
                    target_screen = s
                    break

        if target_screen:
            rect = target_screen.geometry()
            self.setGeometry(rect)

    def _load_theme(self):
        fp = THEMES_DIR / self.theme_name / "theme.json"
        return load_overlay_theme(fp)

    def _get_color(self, name: str, default: str):
        return QColor(self.theme.get(name, default))

    def _update_from_disk(self):
        # Party & Combat Data
        try:
            mtime = os.path.getmtime(PARTY_FP)
            if mtime > self.last_party_mod:
                with open(PARTY_FP, "r") as f:
                    data = json.load(f)
                    self.combatants = data.get("party", [])
                    self.turn_index = data.get("turn_index", -1)
                    self.round = data.get("round", 1)

                self.last_party_mod = mtime
                self._load_portraits()
                presentations = getattr(self, "dialog_presentations", [])
                if presentations:
                    self._load_dialog_portraits(presentations)
                self._load_status_icons()
                self.repaint()
        except (FileNotFoundError, json.JSONDecodeError):
            pass

        # Config (poll_ms / auto_refresh / theme / overlay placement)
        try:
            cfg_m = os.path.getmtime(CONFIG_FP)
            if cfg_m > self.last_cfg_mod:
                with open(CONFIG_FP, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                ov = cfg.get("overlay") or {}
                poll_ms = max(100, int(cfg.get("poll_ms", 200)))
                auto = bool(cfg.get("auto_refresh", True))
                show_secondary = config_bool(cfg.get("show_secondary_combat_metrics"), False)
                if show_secondary != self.show_secondary_combat_metrics:
                    self.show_secondary_combat_metrics = show_secondary
                    self.repaint()
                enemy_disclosure = normalize_enemy_health_disclosure(
                    cfg.get("enemy_health_disclosure")
                )
                if enemy_disclosure != getattr(
                    self, "enemy_health_disclosure", "condition"
                ):
                    self.enemy_health_disclosure = enemy_disclosure
                    self.repaint()
                self.timer.setInterval(poll_ms)
                if auto and not self.timer.isActive():
                    self.timer.start()
                if not auto and self.timer.isActive():
                    self.timer.stop()
                # Theme live update
                new_theme = str(cfg.get("theme", self.theme_name) or self.theme_name)
                if new_theme != self.theme_name:
                    self.theme_name = new_theme
                    self.theme = self._load_theme()
                    self.repaint()
                # Fit mode live update
                new_fit = (ov.get("fit") or self.fit_mode)
                if new_fit != self.fit_mode:
                    self.set_fit_mode(new_fit)
                # Screen + fullscreen placement
                new_screen = ov.get("screen")
                if new_screen != self._cfg_screen:
                    self._cfg_screen = new_screen
                    self.move_to_screen(new_screen)
                new_full = bool(ov.get("fullscreen", True))
                if new_full != self._cfg_fullscreen:
                    self._cfg_fullscreen = new_full
                    if new_full:
                        self.showFullScreen()
                    else:
                        self.showNormal()
                        self.move_to_screen(self._cfg_screen)
                # Mode (combat vs dialog) - controls what overlay displays
                new_mode = str(cfg.get("mode", "combat") or "combat")
                if new_mode != self.mode:
                    self.set_presentation_mode(new_mode)
                self.last_cfg_mod = cfg_m
        except Exception:
            pass

        # Dialog Data
        try:
            mtime = os.path.getmtime(DIALOG_FP)
            if mtime > self.last_dialog_mod:
                with open(DIALOG_FP, "r", encoding="utf-8") as f:
                    content = f.read()
                    self.dialog = content.split("\n---\n")
                self.last_dialog_mod = mtime
                # Reset typing effect when dialog content changes
                self._reset_typing_effect()
                self.repaint()
        except FileNotFoundError:
            self.dialog = []
            self._dialog_typing_timer.stop()
            self._dialog_typing_text = ""
            self._dialog_typing_index = 0
            self._dialog_typing_line_index = 0
            self._dialog_typing_char_index = 0

        # Rich live dialog blocks provide speaker names. Body text continues to
        # come from dialog.txt so this read-only enrichment does not change the
        # established compatibility precedence for externally authored text.
        try:
            blocks_mtime = os.path.getmtime(DIALOG_BLOCKS)
            if blocks_mtime > getattr(self, "last_dialog_blocks_mod", 0):
                with open(DIALOG_BLOCKS, "r", encoding="utf-8") as source:
                    blocks = json.load(source)
                if not isinstance(blocks, list) or not all(
                    isinstance(block, dict) for block in blocks
                ):
                    raise ValueError("dialog blocks must be a list of objects")
                self.dialog_speakers = [
                    str(block.get("speaker") or "") for block in blocks
                ]
                self.dialog_presentations = [dict(block) for block in blocks]
                self._load_dialog_portraits(blocks)
                self.last_dialog_blocks_mod = blocks_mtime
                self.repaint()
        except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError, ValueError):
            pass

        try:
            mtime = os.path.getmtime(DIALOG_FP.with_suffix(".json"))
            with open(DIALOG_FP.with_suffix(".json"), "r") as f:
                data = json.load(f)
                new_idx = data.get("index", -1)
                # Reset typing effect if dialog index changed
                if new_idx != self.dialog_idx:
                    self.dialog_idx = new_idx
                    self._reset_typing_effect()
                else:
                    self.dialog_idx = new_idx
        except (FileNotFoundError, json.JSONDecodeError):
            pass
    
    def _reset_typing_effect(self):
        """Reset typing effect when dialog changes."""
        if self.dialog and 0 <= self.dialog_idx < len(self.dialog):
            self._dialog_typing_text = self.dialog[self.dialog_idx]
            self._dialog_typing_index = 0
            self._dialog_typing_line_index = 0
            self._dialog_typing_char_index = 0
            self._dialog_typing_timer.start()
        else:
            self._dialog_typing_timer.stop()
            self._dialog_typing_text = ""
            self._dialog_typing_index = 0
            self._dialog_typing_line_index = 0
            self._dialog_typing_char_index = 0
    
    def _advance_typing(self):
        """Advance one character within one line, then continue to the next."""
        lines = self._dialog_typing_text.split("\n")
        line_index = getattr(self, "_dialog_typing_line_index", 0)
        char_index = getattr(self, "_dialog_typing_char_index", 0)
        if line_index >= len(lines):
            self._dialog_typing_timer.stop()
            return
        current = lines[line_index]
        if char_index < len(current):
            char_index += 1
        else:
            line_index += 1
            char_index = 0
        self._dialog_typing_line_index = line_index
        self._dialog_typing_char_index = char_index
        self._dialog_typing_index = len(
            dialog_line_reveal(self._dialog_typing_text, line_index, char_index)
        )
        self.repaint()
        if line_index >= len(lines):
            self._dialog_typing_timer.stop()

    def _load_portraits(self):
        self.portraits.clear()
        for c in self.combatants:
            _entry, pixmap, path = resolve_entity_portrait(c)
            if pixmap is not None:
                self.portraits[id(c)] = pixmap
                if c.get("portrait"):
                    self.portraits[c.get("portrait")] = pixmap
                if path is not None:
                    self.portraits[str(path)] = pixmap

    def _dialog_portrait_entities(self):
        entities = list(self.combatants)
        for source in ROSTERS_DIR.glob("*.json"):
            try:
                with open(source, "r", encoding="utf-8") as stream:
                    document = json.load(stream)
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if isinstance(document, list):
                entries = document
            elif isinstance(document, dict):
                entries = next(
                    (
                        document.get(key)
                        for key in ("roster", "characters", "creatures", "monsters", "entries")
                        if isinstance(document.get(key), list)
                    ),
                    [],
                )
            else:
                entries = []
            for raw in entries:
                if isinstance(raw, dict):
                    entity = dict(raw)
                    entity.setdefault(
                        PORTRAIT_SOURCE_DIR_FIELD, str(source.resolve().parent)
                    )
                    entities.append(entity)
        return entities

    def _load_dialog_portraits(self, blocks):
        self.dialog_portraits = {}
        entities = self._dialog_portrait_entities()
        for index, block in enumerate(blocks):
            pixmap, path, _source = resolve_dialog_portrait(block, entities)
            if pixmap is None:
                continue
            self.dialog_portraits[("index", index)] = pixmap
            self.dialog_portraits[block.get("id") or id(block)] = pixmap
            if block.get("portrait"):
                self.dialog_portraits[block.get("portrait")] = pixmap
            if path is not None:
                self.dialog_portraits[str(path)] = pixmap

    def _load_status_icons(self):
        self.status_icons.clear()
        if STATUS_DIR.is_dir():
            for f in STATUS_DIR.iterdir():
                if f.suffix.lower() in (".png", ".svg"):
                    pix = QPixmap(str(f))
                    if not pix.isNull():
                        self.status_icons[f.stem.lower()] = pix  # scale at draw time


    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # Apply a scale transformation for base resolution
        s_w, s_h, t_x, t_y = _compute_fit(BASE_W, BASE_H, self.width(), self.height(), self.fit_mode)
        p.translate(t_x, t_y)
        p.scale(s_w, s_h)

        # Transparent by default; if you later add optional background image/video,
        # draw it here. For now, keep fully transparent.
        # p.fillRect(QRect(0, 0, BASE_W, BASE_H), QBrush(self._get_color("bg", "#000000")))

        self._draw_active_mode(p)

        p.end()

    def _draw_active_mode(self, p: QPainter):
        progress = getattr(self, "_scene_transition_progress", 1.0)
        previous = getattr(self, "_transition_from_mode", self.mode)
        if progress < 1.0 and previous != self.mode:
            p.save()
            p.setOpacity(max(0.0, 1.0 - progress))
            p.translate(round(-28 * progress), 0)
            Overlay._draw_mode(self, p, previous)
            p.restore()
            p.save()
            p.setOpacity(progress)
            p.translate(round(28 * (1.0 - progress)), 0)
            Overlay._draw_mode(self, p, self.mode)
            p.restore()
            return
        Overlay._draw_mode(self, p, self.mode)

    def _draw_mode(self, p: QPainter, mode: str):
        if mode == "combat":
            self._draw_combat(p)
        elif mode == "dialog":
            self._draw_dialog(p)

    def _draw_combat(self, p: QPainter):
        if not self.combatants:
            return
        renderer_mode = self.theme.get("renderer_mode", "gm_modern")
        density = combat_density(len(self.combatants))
        base_size = max(
            10,
            self.theme.get("font_base_size", 16) - density["font_reduction"],
        )
        small_size = max(
            8,
            self.theme.get("font_small_size", 10) - density["font_reduction"],
        )
        name_font = QFont(self.theme.get("font_combat_name","Arial"), base_size)
        metric_font = QFont(self.theme.get("font_combat_hp","Arial"), small_size + 1)
        badge_font = QFont(self.theme.get("font_combat_hp","Arial"), small_size)
        initiative_font = QFont(
            self.theme.get("font_combat_init", "Arial"), small_size
        )
        name_fm = QFontMetrics(name_font)
        metric_fm = QFontMetrics(metric_font)
        badge_fm = QFontMetrics(badge_font)
        initiative_fm = QFontMetrics(initiative_font)
        gap = density["gap"]
        pad = density["padding"]
        portrait_size = density["portrait_size"]
        badge_pad_x = max(6, badge_fm.height() // 2)
        badge_gap = max(4, badge_fm.height() // 3)

        # The declared region remains a placement boundary. Only cards are painted.
        right_x, right_y, right_w, _right_h = overlay_region_rect(
            self.theme, "right_column", BASE_W, BASE_H
        )
        progression_h = initiative_fm.height() + 12
        progression_rect = QRect(right_x, right_y, right_w, progression_h)
        progression_text = combat_progression_text(
            self.combatants,
            self.turn_index,
            getattr(self, "round", 1),
        )
        p.setFont(initiative_font)
        p.setPen(QPen(self._get_color("panel_border", "#4A4A4A"), 1))
        p.drawLine(
            progression_rect.bottomLeft(),
            progression_rect.bottomRight(),
        )
        p.setPen(self._get_color("speaker_text", "#FFFFFF"))
        rendered_progression = (
            progression_text.replace("ROUND ", "[ROUND ").replace("  •  ", "]  ")
            if renderer_mode == "rpg_retro"
            else progression_text
        )
        p.drawText(
            progression_rect.adjusted(pad, 0, -pad, 0),
            Qt.AlignLeft | Qt.AlignVCenter,
            rendered_progression,
        )
        has_portrait_column = any(
            bool(
                self.portraits.get(id(combatant))
                or self.portraits.get(combatant.get("portrait"))
            )
            for combatant in self.combatants
        )
        portrait_column = portrait_size + pad if has_portrait_column else 0
        content_x = right_x + pad + portrait_column
        content_w = max(80, right_w - (content_x - right_x) - pad)

        layouts = []
        for m in self.combatants:
            statuses = [
                condition_display_label(renderer_mode, status)
                for status in (m.get("statuses") or [])
            ]
            condition_padding = (
                badge_pad_x
                if renderer_mode == "gm_modern"
                else (4 if renderer_mode == "rpg_retro" else 0)
            )
            rows = status_badge_rows(
                statuses,
                content_w,
                badge_fm.horizontalAdvance,
                badge_gap,
                condition_padding,
                max_rows=density["condition_rows"],
            )
            initiative = m.get("initTotal")
            initiative_text = f"INIT {initiative if initiative is not None else '—'}"
            initiative_width = max(
                initiative_fm.horizontalAdvance("INIT 000"),
                initiative_fm.horizontalAdvance(initiative_text),
            )
            name_width = max(40, content_w - initiative_width - gap)
            name_lines = _wrapped_lines(m.get("name", "???"), name_width, name_fm)
            is_enemy = (m.get("side") or "Enemy").lower() == "enemy"
            disclosure = (
                normalize_enemy_health_disclosure(
                    getattr(self, "enemy_health_disclosure", "condition")
                )
                if is_enemy
                else "full"
            )
            metric_rows = (
                combatant_metric_displays(
                    m,
                    include_secondary=self.show_secondary_combat_metrics,
                    respect_overlay_visibility=True,
                )
                if disclosure == "full"
                else []
            )
            descriptor = enemy_health_descriptor(m) if disclosure == "condition" else ""
            badge_h = badge_fm.height() + max(6, badge_fm.height() // 2)
            name_h = len(name_lines) * name_fm.height() + gap * max(0, len(name_lines) - 1)
            condition_h = len(rows) * badge_h + gap * len(rows)
            metric_row_count = len(metric_rows) + (1 if descriptor else 0)
            metrics_h = (
                metric_row_count * metric_fm.height()
                + gap * max(0, metric_row_count - 1)
            )
            text_h = (
                name_h
                + max(0, initiative_fm.height() - name_fm.height())
                + (gap if rows or descriptor or metric_rows else 0)
                + condition_h
                + metrics_h
            )
            portrait = self.portraits.get(id(m)) or self.portraits.get(m.get("portrait"))
            portrait_h = portrait_size + pad * 2 if portrait else 0
            card_h = max(portrait_h, text_h + pad * 2)
            layouts.append(
                (
                    card_h,
                    name_lines,
                    rows,
                    initiative_text,
                    initiative_width,
                    name_width,
                    metric_rows,
                    descriptor,
                )
            )

        y = progression_rect.bottom() + gap + 1
        for i, m in enumerate(self.combatants):
            (
                card_h,
                name_lines,
                status_rows,
                initiative_text,
                initiative_width,
                name_width,
                metric_rows,
                descriptor,
            ) = layouts[i]
            card = QRect(right_x, y, right_w, card_h)
            # side colors
            side = (m.get("side") or "Enemy").lower()
            bg = self._get_color("enemy_bg","#2A2A2A") if side=="enemy" else \
                 self._get_color("friendly_bg","#2A2A2A") if side=="friendly" else \
                 self._get_color("neutral_bg","#2A2A2A")
            fg = self._get_color("enemy_text","#F08080") if side=="enemy" else \
                 self._get_color("friendly_text","#77DD77") if side=="friendly" else \
                 self._get_color("neutral_text","#FADFAD")

            # card with rounded corners
            card_bg = QColor(bg)
            card_bg.setAlpha(235)
            p.setBrush(QBrush(card_bg))
            pen = QPen(fg)
            pen.setWidth(1 if renderer_mode == "dark_parchment" else 2)
            p.setPen(pen)
            card_inner = card.adjusted(4, 4, -4, -4)
            if renderer_mode == "dark_parchment":
                p.setPen(Qt.NoPen)
                p.drawRect(card_inner)
                p.setPen(QPen(fg, 1))
                p.drawLine(card_inner.bottomLeft(), card_inner.bottomRight())
            elif renderer_mode == "rpg_retro":
                p.drawRect(card_inner)
            else:
                p.drawRoundedRect(card_inner, 10, 10)

            # portrait (optional)
            px = card.x() + pad
            py = card.y() + (card_h - portrait_size) // 2
            por = m.get("portrait")
            pix = self.portraits.get(id(m))
            if pix is None and por:
                pix = self.portraits.get(por) or self.portraits.get(str(por))
            if pix and not pix.isNull():
                target = QRect(px, py, portrait_size, portrait_size)
                p.drawPixmap(
                    target,
                    pix.scaled(
                        target.size(),
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation,
                    ),
                )

            # name, conditions, then metric rows
            name_x = content_x
            cursor_y = card.y() + pad
            p.setPen(self._get_color("text","#FFFFFF"))
            p.setFont(name_font)
            for line_index, line in enumerate(name_lines):
                p.drawText(QRect(name_x, cursor_y, name_width, name_fm.height()),
                           Qt.AlignLeft|Qt.AlignVCenter, line)
                cursor_y += name_fm.height()
                if line_index < len(name_lines) - 1:
                    cursor_y += gap
            if status_rows or descriptor or metric_rows:
                cursor_y += gap
            p.setFont(initiative_font)
            p.drawText(
                QRect(
                    name_x + content_w - initiative_width,
                    card.y() + pad,
                    initiative_width,
                    initiative_fm.height(),
                ),
                Qt.AlignRight | Qt.AlignVCenter,
                initiative_text,
            )

            p.setFont(badge_font)
            for row in status_rows:
                badge_x = name_x
                badge_h = badge_fm.height() + max(6, badge_fm.height() // 2)
                for label in row:
                    condition_padding = (
                        badge_pad_x
                        if renderer_mode == "gm_modern"
                        else (4 if renderer_mode == "rpg_retro" else 0)
                    )
                    badge_w = badge_fm.horizontalAdvance(label) + condition_padding * 2
                    badge = QRect(badge_x, cursor_y, badge_w, badge_h)
                    if renderer_mode == "gm_modern":
                        p.setPen(QPen(self._get_color("condition_border", "#C8C8C8"), 1))
                        condition_bg = self._get_color("condition_bg", "#282828")
                        condition_bg.setAlpha(210)
                        p.setBrush(QBrush(condition_bg))
                        p.drawRoundedRect(badge, badge_h // 3, badge_h // 3)
                    p.setPen(self._get_color("condition_text", "#FFFFFF"))
                    p.drawText(badge, Qt.AlignCenter, label)
                    badge_x += badge_w + badge_gap
                cursor_y += badge_h + gap

            p.setFont(metric_font)
            if descriptor:
                p.setPen(self._get_color("condition_text", "#FFFFFF"))
                p.drawText(
                    QRect(name_x, cursor_y, content_w, metric_fm.height()),
                    Qt.AlignLeft | Qt.AlignVCenter,
                    descriptor,
                )
                cursor_y += metric_fm.height() + gap

            for current, maximum, metric_label in metric_rows:
                ratio = current / maximum
                label_w = max(metric_fm.horizontalAdvance(metric_label), metric_fm.horizontalAdvance("Stamina"))
                value = f"{current}/{maximum}"
                value_w = max(
                    metric_fm.horizontalAdvance(value),
                    metric_fm.horizontalAdvance("0000/0000"),
                )
                bar_x = name_x + label_w + gap
                bar_w = max(24, content_w - label_w - value_w - gap * 2)
                bar_h = max(10, metric_fm.height() // 2)
                bar_y = cursor_y + max(0, (metric_fm.height() - bar_h) // 2)
                p.setPen(self._get_color("text","#FFFFFF"))
                p.drawText(QRect(name_x, cursor_y, label_w, metric_fm.height()),
                           Qt.AlignLeft|Qt.AlignVCenter, metric_label)
                geometry = metric_bar_geometry(
                    renderer_mode, QRect(bar_x, bar_y, bar_w, bar_h), ratio
                )
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(self._get_color("metric_track", "#282828")))
                for segment in geometry["track"]:
                    if renderer_mode == "gm_modern":
                        p.drawRoundedRect(segment, 2, 2)
                    else:
                        p.drawRect(segment)
                p.setBrush(QBrush(self._get_color("metric_fill", "#28C878")))
                for segment in geometry["fill"]:
                    if renderer_mode == "gm_modern":
                        p.drawRoundedRect(segment, 2, 2)
                    else:
                        p.drawRect(segment)
                p.setPen(self._get_color("text","#FFFFFF"))
                p.drawText(QRect(bar_x + bar_w + gap, cursor_y, value_w, metric_fm.height()),
                           Qt.AlignRight|Qt.AlignVCenter, value)
                cursor_y += metric_fm.height() + gap

            # active badge (turn)
            if i == self.turn_index:
                active = self._get_color("turn_bg", "#FFD700")
                if renderer_mode == "dark_parchment":
                    p.setPen(QPen(active, 2))
                    p.drawLine(card_inner.topLeft(), card_inner.topRight())
                elif renderer_mode == "rpg_retro":
                    p.setPen(QPen(active, 3))
                    p.setBrush(Qt.NoBrush)
                    p.drawRect(card_inner)
                    p.drawText(
                        QRect(card.x() - 52, card.y(), 48, card_h),
                        Qt.AlignVCenter | Qt.AlignRight,
                        f"> {(self.turn_index or 0) + 1}",
                    )
                else:
                    badge = QRect(card.x()-10, card.y()+8, 8, card_h-16)
                    p.setPen(Qt.NoPen)
                    p.setBrush(QBrush(active))
                    p.drawRoundedRect(badge, 4, 4)
                if renderer_mode != "rpg_retro":
                    p.setPen(QPen(self._get_color("text", "#FFFFFF")))
                    p.drawText(
                        QRect(card.x()-44, card.y(), 32, card_h),
                        Qt.AlignVCenter | Qt.AlignRight,
                        str((self.turn_index or 0)+1),
                    )

            y += card_h + gap

    def _draw_dialog(self, p: QPainter):
        if not self.dialog:
            return
        renderer_mode = self.theme.get("renderer_mode", "gm_modern")
        
        # Draw smaller ally combat metric bars and status icons during dialog mode (before dialog box)
        self._draw_dialog_allies(p)
        if not 0 <= self.dialog_idx < len(self.dialog):
            return
        idx = self.dialog_idx
        # Use typing effect text if available, otherwise full text
        if self._dialog_typing_text and idx == self.dialog_idx:
            if hasattr(self, "_dialog_typing_line_index"):
                text = dialog_line_reveal(
                    self._dialog_typing_text,
                    self._dialog_typing_line_index,
                    self._dialog_typing_char_index,
                )
            else:
                text = self._dialog_typing_text[:self._dialog_typing_index]
        else:
            text = self.dialog[idx]
            # Initialize typing effect if needed
            if not self._dialog_typing_text or idx != self.dialog_idx:
                self._reset_typing_effect()
                if self._dialog_typing_text:
                    text = dialog_line_reveal(
                        self._dialog_typing_text,
                        getattr(self, "_dialog_typing_line_index", 0),
                        getattr(self, "_dialog_typing_char_index", 0),
                    )
        speakers = getattr(self, "dialog_speakers", [])
        speaker = speakers[idx] if 0 <= idx < len(speakers) else ""
        region = QRect(
            *overlay_region_rect(self.theme, "dialog_box", BASE_W, BASE_H)
        )

        body_font = QFont(
            self.theme.get("font_dialog","Arial"),
            self.theme.get("font_dialog_size", 18),
        )
        speaker_font = QFont(
            self.theme.get("font_combat_name", "Arial"),
            self.theme.get("font_base_size", 16),
        )
        speaker_font.setBold(True)
        body_fm = QFontMetrics(body_font)
        speaker_fm = QFontMetrics(speaker_font)
        horizontal_padding = 16
        vertical_padding = 12
        line_gap = 6
        content_width = max(1, region.width() - horizontal_padding * 2)
        lines = _wrapped_lines(text, content_width, body_fm)
        speaker_height = speaker_fm.height() + line_gap if speaker else 0
        body_height = (
            len(lines) * body_fm.height()
            + max(0, len(lines) - 1) * line_gap
        )
        required_height = (
            vertical_padding * 2 + speaker_height + body_height
        )
        available_height = max(1, region.bottom() + 1 - vertical_padding)
        dialog_height = max(
            vertical_padding * 2 + body_fm.height(),
            min(required_height, available_height),
        )
        dlg = QRect(
            region.x(),
            region.bottom() - dialog_height + 1,
            region.width(),
            dialog_height,
        )

        presentations = getattr(self, "dialog_presentations", [])
        presentation = (
            presentations[idx]
            if 0 <= idx < len(presentations)
            and isinstance(presentations[idx], dict)
            else {}
        )
        portrait_key = presentation.get("id") or id(presentation)
        portrait = getattr(self, "dialog_portraits", {}).get(("index", idx))
        if portrait is None:
            portrait = getattr(self, "dialog_portraits", {}).get(portrait_key)
        if portrait is None:
            portrait = getattr(self, "dialog_portraits", {}).get(
                presentation.get("portrait")
            )
        if portrait and not portrait.isNull():
            portrait_rect, mirror = dialog_portrait_geometry(
                dlg, portrait.size(), presentation
            )
            rendered_portrait = (
                portrait.transformed(
                    QTransform().scale(-1, 1),
                    Qt.SmoothTransformation,
                )
                if mirror
                else portrait
            )
            p.drawPixmap(portrait_rect, rendered_portrait)

        bg = self._get_color("dialog_bg", "#121212")
        bdr = self._get_color("dialog_bdr", "#333333")
        # The opaque panel masks the lower portion of a portrait cut-in.
        bg.setAlpha(255)
        p.setBrush(QBrush(bg))
        if renderer_mode == "dark_parchment":
            p.setPen(Qt.NoPen)
            p.drawRect(dlg)
            p.setPen(QPen(bdr, 1))
            p.drawLine(dlg.topLeft(), dlg.topRight())
            p.drawLine(dlg.bottomLeft(), dlg.bottomRight())
        elif renderer_mode == "rpg_retro":
            p.setPen(QPen(bdr, 2))
            p.drawRect(dlg)
        else:
            p.setPen(QPen(bdr, 2))
            p.drawRoundedRect(dlg, 14, 14)

        content = dlg.adjusted(
            horizontal_padding,
            vertical_padding,
            -horizontal_padding,
            -vertical_padding,
        )
        body_y = content.y()
        if speaker:
            p.setPen(self._get_color("speaker_text", "#FFFFFF"))
            p.setFont(speaker_font)
            p.drawText(
                QRect(content.x(), body_y, content.width(), speaker_fm.height()),
                Qt.AlignLeft | Qt.AlignVCenter,
                speaker,
            )
            body_y += speaker_fm.height() + line_gap

        p.setPen(self._get_color("text", "#FFFFFF"))
        p.setFont(body_font)
        available_height = max(0, content.bottom() - body_y + 1)
        max_lines = max(
            1,
            (available_height + line_gap)
            // max(1, body_fm.height() + line_gap),
        )
        for line_index, line in enumerate(lines[:max_lines]):
            p.drawText(
                QRect(
                    content.x(),
                    body_y + line_index * (body_fm.height() + line_gap),
                    content.width(),
                    body_fm.height(),
                ),
                Qt.AlignLeft | Qt.AlignVCenter,
                line,
            )
    
    def _draw_dialog_allies(self, p: QPainter):
        """Draw smaller combat metric bars and status icons for allies during dialog mode."""
        allies = [c for c in self.combatants if (c.get("side") or "Enemy").lower() == "friendly"]
        if not allies:
            return
        renderer_mode = self.theme.get("renderer_mode", "gm_modern")
        
        # Small compact display at top-left during dialog
        start_x = int(BASE_W * 0.05)
        start_y = int(BASE_H * 0.05)
        card_w = 240
        small_size = self.theme.get("font_small_size", 10)
        name_font = QFont(self.theme.get("font_combat_name", "Arial"), small_size + 1)
        metric_font = QFont(self.theme.get("font_combat_hp", "Arial"), max(6, small_size - 1))
        badge_font = QFont(self.theme.get("font_combat_hp", "Arial"), max(6, small_size - 2))
        initiative_font = QFont(
            self.theme.get("font_combat_init", "Arial"), max(6, small_size - 1)
        )
        name_fm = QFontMetrics(name_font)
        metric_fm = QFontMetrics(metric_font)
        badge_fm = QFontMetrics(badge_font)
        initiative_fm = QFontMetrics(initiative_font)
        gap = max(4, metric_fm.height() // 3)
        pad = max(6, name_fm.height() // 3)
        content_w = card_w - pad * 2
        badge_pad_x = max(6, badge_fm.height() // 2)
        badge_gap = max(4, badge_fm.height() // 3)
        
        layouts = []
        for ally in allies[:5]:
            statuses = [
                condition_display_label(renderer_mode, status)
                for status in (ally.get("statuses") or [])
            ]
            condition_padding = (
                badge_pad_x
                if renderer_mode == "gm_modern"
                else (4 if renderer_mode == "rpg_retro" else 0)
            )
            status_rows = status_badge_rows(
                statuses,
                content_w,
                badge_fm.horizontalAdvance,
                badge_gap,
                condition_padding,
                max_rows=1,
            )
            initiative = ally.get("initTotal")
            initiative_text = f"INIT {initiative if initiative is not None else '—'}"
            initiative_width = max(
                initiative_fm.horizontalAdvance("INIT 000"),
                initiative_fm.horizontalAdvance(initiative_text),
            )
            name_width = max(32, content_w - initiative_width - gap)
            name_lines = _wrapped_lines(ally.get("name", "???"), name_width, name_fm)
            metric_count = len(combatant_metric_displays(
                ally,
                include_secondary=self.show_secondary_combat_metrics,
                respect_overlay_visibility=True,
            ))
            card_h = (
                pad * 2
                + len(name_lines) * name_fm.height()
                + max(0, initiative_fm.height() - name_fm.height())
                + len(status_rows) * (badge_fm.height() + max(4, badge_fm.height() // 2))
                + metric_count * (metric_fm.height() + gap)
                + gap * max(0, len(name_lines) - 1 + len(status_rows))
            )
            layouts.append(
                (
                    card_h,
                    name_lines,
                    status_rows,
                    initiative_text,
                    initiative_width,
                    name_width,
                )
            )

        y = start_y
        for i, ally in enumerate(allies[:5]):  # Max 5 allies shown
            (
                card_h,
                name_lines,
                status_rows,
                initiative_text,
                initiative_width,
                name_width,
            ) = layouts[i]
            card = QRect(start_x, y, card_w, card_h)
            
            # Background
            bg = self._get_color("friendly_bg", "#2A2A2A")
            bg.setAlpha(200)
            p.setBrush(QBrush(bg))
            p.setPen(QPen(self._get_color("friendly_text", "#77DD77"), 1))
            if renderer_mode == "dark_parchment":
                p.setPen(Qt.NoPen)
                p.drawRect(card)
                p.setPen(QPen(self._get_color("friendly_text", "#77DD77"), 1))
                p.drawLine(card.bottomLeft(), card.bottomRight())
            elif renderer_mode == "rpg_retro":
                p.drawRect(card)
            else:
                p.drawRoundedRect(card, 6, 6)
            
            # Name
            p.setPen(self._get_color("text", "#FFFFFF"))
            p.setFont(name_font)
            cursor_y = card.y() + pad
            for line in name_lines:
                p.drawText(QRect(card.x() + pad, cursor_y, name_width, name_fm.height()),
                           Qt.AlignLeft | Qt.AlignVCenter, line)
                cursor_y += name_fm.height() + gap
            p.setFont(initiative_font)
            p.drawText(
                QRect(
                    card.x() + pad + content_w - initiative_width,
                    card.y() + pad,
                    initiative_width,
                    initiative_fm.height(),
                ),
                Qt.AlignRight | Qt.AlignVCenter,
                initiative_text,
            )

            p.setFont(badge_font)
            for row in status_rows:
                badge_x = card.x() + pad
                badge_h = badge_fm.height() + max(4, badge_fm.height() // 2)
                for label in row:
                    condition_padding = (
                        badge_pad_x
                        if renderer_mode == "gm_modern"
                        else (4 if renderer_mode == "rpg_retro" else 0)
                    )
                    badge_w = badge_fm.horizontalAdvance(label) + condition_padding * 2
                    badge = QRect(badge_x, cursor_y, badge_w, badge_h)
                    if renderer_mode == "gm_modern":
                        p.setPen(QPen(self._get_color("condition_border", "#C8C8C8"), 1))
                        condition_bg = self._get_color("condition_bg", "#282828")
                        condition_bg.setAlpha(210)
                        p.setBrush(QBrush(condition_bg))
                        p.drawRoundedRect(badge, badge_h // 3, badge_h // 3)
                    p.setPen(self._get_color("condition_text", "#FFFFFF"))
                    p.drawText(badge, Qt.AlignCenter, label)
                    badge_x += badge_w + badge_gap
                cursor_y += badge_h + gap

            p.setFont(metric_font)
            for current, maximum, metric_label in combatant_metric_displays(
                ally,
                include_secondary=self.show_secondary_combat_metrics,
                respect_overlay_visibility=True,
            ):
                label = f"{metric_label} {current}/{maximum}"
                p.setPen(self._get_color("text", "#FFFFFF"))
                p.drawText(QRect(card.x() + pad, cursor_y, content_w, metric_fm.height()),
                           Qt.AlignLeft | Qt.AlignVCenter, label)
                cursor_y += metric_fm.height() + gap
            y += card_h + gap


def run_standalone(argv=None) -> int:
    """Development entry point; reuse an existing QApplication when embedded."""
    app = QApplication.instance()
    owns_application = app is None
    if app is None:
        app = QApplication(list(argv if argv is not None else sys.argv))
    overlay_runtime_log(
        f"Standalone overlay requested owns_qapplication={owns_application}"
    )
    try:
        window = Overlay()
        app.setProperty("encounterosStandaloneOverlay", window)
        window.showFullScreen()
        overlay_runtime_log("Standalone overlay shown")
    except Exception as error:
        overlay_runtime_log("Standalone overlay initialization failed", error)
        return 1
    return app.exec() if owns_application else 0


if __name__ == "__main__":
    raise SystemExit(run_standalone())
