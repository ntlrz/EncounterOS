# tracker_overlay.py — EncounterOS overlay HUD. Reads party/config/dialog + themes and paints HUD.
# Compatible with the GM UI posted (auto-refresh, theme hot-reload, enemy status icons).
import json, os, sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QRect, QSize, QPoint
from PySide6.QtGui import QPainter, QColor, QBrush, QPen, QFont, QPixmap, QGuiApplication, QFontMetrics
from PySide6.QtWidgets import QApplication, QWidget
from app_paths import APP_DIR, PARTY_FP, CONFIG_FP, DIALOG_FP, DIALOGMETA, THEMES_DIR, STATUS_DIR

BASE_W, BASE_H = 1280, 720
ICON_SIZE = QSize(64,64)
STATUS_ICON_SZ = QSize(24,24)

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
        self.theme = self._load_theme()

        self.combatants = []
        self.turn_index = -1
        self.round = 1
        self.dialog = []
        self.dialog_idx = -1
        self.last_party_mod = 0
        self.last_dialog_mod = 0
        self.portraits = {}
        self.status_icons = {}
        self.mode = "combat"  # "combat" or "dialog" - controls what overlay shows
        # Typing effect for dialog
        self._dialog_typing_text = ""
        self._dialog_typing_index = 0
        self._dialog_typing_timer = QTimer(self)
        self._dialog_typing_timer.setInterval(30)  # 30ms per character = fast typing
        self._dialog_typing_timer.timeout.connect(self._advance_typing)

        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._update_from_disk)
        self.timer.start()
        
        self.last_cfg_mod = 0

        self._update_from_disk()

    def set_fit_mode(self, mode: str):
        self.fit_mode = mode
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
        fallback_theme = {
            "bg": "#000000",
            "combat_bg": "#121212",
            "combat_bdr": "#333333",
            "dialog_bg": "#121212",
            "dialog_bdr": "#333333",
            "turn_bg": "#4A4A4A",
            "friendly_bg": "#2A2A2A",
            "friendly_text": "#77DD77",
            "enemy_bg": "#2A2A2A",
            "enemy_text": "#F08080",
            "neutral_bg": "#2A2A2A",
            "neutral_text": "#FADFAD",
            "text": "#FFFFFF",
            "font_combat_name": "Arial",
            "font_combat_hp": "Arial",
            "font_combat_init": "Arial",
            "font_dialog": "Arial",
        }
        try:
            with open(fp, "r", encoding="utf-8") as f:
                theme_data = json.load(f)
                # Handle nested structure (vars.colors, vars.fonts) or flat structure
                flat_theme = {}
                if "vars" in theme_data:
                    colors = theme_data.get("vars", {}).get("colors", {})
                    fonts = theme_data.get("vars", {}).get("fonts", {})
                    # Map nested structure to flat keys
                    flat_theme["combat_bg"] = colors.get("card_bg", fallback_theme["combat_bg"])
                    flat_theme["combat_bdr"] = colors.get("border_idle", fallback_theme["combat_bdr"])
                    flat_theme["dialog_bg"] = colors.get("dialog_bg", fallback_theme["dialog_bg"])
                    flat_theme["dialog_bdr"] = colors.get("dialog_border", fallback_theme["dialog_bdr"])
                    flat_theme["turn_bg"] = colors.get("border_active", fallback_theme["turn_bg"])
                    flat_theme["text"] = colors.get("text", fallback_theme["text"])
                    flat_theme["friendly_bg"] = colors.get("card_bg", fallback_theme["friendly_bg"])
                    flat_theme["enemy_bg"] = colors.get("card_bg", fallback_theme["enemy_bg"])
                    flat_theme["neutral_bg"] = colors.get("card_bg", fallback_theme["neutral_bg"])
                    flat_theme["friendly_text"] = colors.get("hp_good", fallback_theme["friendly_text"])
                    flat_theme["enemy_text"] = colors.get("hp_back", fallback_theme["enemy_text"])
                    flat_theme["neutral_text"] = colors.get("text", fallback_theme["neutral_text"])
                    flat_theme["font_combat_name"] = fonts.get("base_family", fallback_theme["font_combat_name"])
                    flat_theme["font_combat_hp"] = fonts.get("base_family", fallback_theme["font_combat_hp"])
                    flat_theme["font_combat_init"] = fonts.get("base_family", fallback_theme["font_combat_init"])
                    flat_theme["font_dialog"] = fonts.get("base_family", fallback_theme["font_dialog"])
                else:
                    # Flat structure - use as-is
                    flat_theme = theme_data
                # Merge with fallback to ensure all keys exist
                return {**fallback_theme, **flat_theme}
        except Exception as e:
            print(f"Error loading theme {self.theme_name}: {e}")
            import traceback
            traceback.print_exc()
            return fallback_theme

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
                    self.mode = new_mode
                    self.repaint()
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
            self._dialog_typing_timer.start()
        else:
            self._dialog_typing_timer.stop()
            self._dialog_typing_text = ""
            self._dialog_typing_index = 0
    
    def _advance_typing(self):
        """Advance typing effect by one character."""
        if self._dialog_typing_index < len(self._dialog_typing_text):
            self._dialog_typing_index += 1
            self.repaint()
        else:
            self._dialog_typing_timer.stop()

    def _load_portraits(self):
        self.portraits.clear()
        for c in self.combatants:
            p_path = c.get("portrait")
            if p_path and Path(p_path).exists():
                pix = QPixmap(p_path)
                if not pix.isNull():
                    self.portraits[p_path] = pix

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

        # Draw based on current mode - only show combat OR dialog, not both
        if self.mode == "combat":
            self._draw_combat(p)
        elif self.mode == "dialog":
            self._draw_dialog(p)

        p.end()

    def _draw_combat(self, p: QPainter):
        if not self.combatants:
            return
        fm = QFontMetrics(QFont(self.theme.get("font_combat_name","Arial"), 16))
        
        # Dynamic sizing: scale panel height based on number of combatants
        card_h = 100
        gap = 10
        num_combatants = len(self.combatants)
        # Calculate needed height: cards + gaps + padding
        needed_h = (card_h * num_combatants) + (gap * max(0, num_combatants - 1)) + 32  # 32px padding
        # Clamp between min and max heights
        min_h = card_h + 32  # At least one card
        max_h = int(BASE_H * 0.85)  # Max 85% of screen height
        panel_h = max(min_h, min(needed_h, max_h))
        
        # Right column region (logical) - dynamically sized
        right = QRect(int(BASE_W*0.65), int(BASE_H*0.05), int(BASE_W*0.30), panel_h)

        # Panel background for the whole combat area (modern card-style container)
        panel = right.adjusted(-16, -16, 12, 16)
        panel_bg = self._get_color("combat_bg", "#121212")
        panel_border = self._get_color("combat_bdr", "#333333")
        panel_bg.setAlpha(220)
        p.setPen(QPen(panel_border, 2))
        p.setBrush(QBrush(panel_bg))
        p.drawRoundedRect(panel, 14, 14)

        y = right.y()
        for i, m in enumerate(self.combatants):
            card = QRect(right.x(), y, right.width(), card_h)
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
            pen.setWidth(2)
            p.setPen(pen)
            p.drawRoundedRect(card.adjusted(4, 4, -4, -4), 10, 10)

            # portrait (optional)
            px = card.x()+16; py = card.y()+(card_h-ICON_SIZE.height())//2
            por = m.get("portrait")
            if por:
                pix = self.portraits.get(por) or self.portraits.get(str(por))
                if pix and not pix.isNull():
                    p.drawPixmap(QRect(px, py, ICON_SIZE.width(), ICON_SIZE.height()), pix)

            # name + hp/status
            name_x = px + ICON_SIZE.width() + 14
            p.setPen(self._get_color("text","#FFFFFF"))
            p.setFont(QFont(self.theme.get("font_combat_name","Arial"), 16))
            p.drawText(QRect(name_x, card.y()+8, card.width()-name_x-8, fm.height()+6),
                       Qt.AlignLeft|Qt.AlignVCenter, m.get("name","???"))

            # HP bar
            hp_max = max(1, int(m.get("hpMax") or 1))
            hp = max(0, min(int(m.get("hp") or 0), hp_max))
            ratio = hp / hp_max
            bar_w = card.width() - (name_x - card.x()) - 14
            bar_h = 18
            bar_x = name_x
            bar_y = card.y()+fm.height()+18
            # background bar
            bg_rect = QRect(bar_x, bar_y, bar_w, bar_h)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(40, 40, 40, 210)))
            p.drawRoundedRect(bg_rect, 6, 6)
            # filled portion
            fill_rect = QRect(bar_x, bar_y, int(bar_w*ratio), bar_h)
            p.setBrush(QBrush(QColor(40, 200, 120, 230)))
            p.drawRoundedRect(fill_rect, 6, 6)
            p.setPen(self._get_color("text","#FFFFFF"))
            p.drawText(bar_x+6, bar_y+bar_h+16, f"{hp}/{hp_max} HP")

            # statuses (right side of bar) - larger icons for better visibility
            icon_w, icon_h = 28, 28  # Larger than default for readability
            sx = bar_x + bar_w - icon_w
            sy = bar_y + (bar_h - icon_h)//2
            for key in (m.get("statuses") or [])[:4]:
                pix = self.status_icons.get(str(key).lower())
                if pix and not pix.isNull():
                    # Draw with a subtle background circle for contrast
                    p.setPen(Qt.NoPen)
                    p.setBrush(QBrush(QColor(0, 0, 0, 120)))
                    p.drawEllipse(QRect(sx-2, sy-2, icon_w+4, icon_h+4))
                    p.drawPixmap(QRect(sx, sy, icon_w, icon_h), pix)
                else:
                    p.setPen(QPen(QColor(200, 200, 200, 200), 2))
                    p.setBrush(QBrush(QColor(100, 100, 100, 180)))
                    p.drawEllipse(QRect(sx, sy, icon_w, icon_h))
                sx -= icon_w + 6

            # active badge (turn)
            if i == self.turn_index:
                badge = QRect(card.x()-10, card.y()+8, 8, card_h-16)
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(self._get_color("turn_bg", "#FFD700")))
                p.drawRoundedRect(badge, 4, 4)
                p.setPen(QPen(QColor("#FFFFFF")))
                p.drawText(QRect(card.x()-44, card.y(), 32, card_h),
                           Qt.AlignVCenter | Qt.AlignRight,
                           str((self.turn_index or 0)+1))

            y += card_h + gap

    def _draw_dialog(self, p: QPainter):
        if not self.dialog:
            return
        
        # Draw smaller ally health bars and status icons during dialog mode (before dialog box)
        self._draw_dialog_allies(p)
        
        idx = self.dialog_idx if (0 <= self.dialog_idx < len(self.dialog)) else 0
        # Use typing effect text if available, otherwise full text
        if self._dialog_typing_text and idx == self.dialog_idx:
            text = self._dialog_typing_text[:self._dialog_typing_index]
        else:
            text = self.dialog[idx]
            # Initialize typing effect if needed
            if not self._dialog_typing_text or idx != self.dialog_idx:
                self._reset_typing_effect()
                if self._dialog_typing_text:
                    text = self._dialog_typing_text[:self._dialog_typing_index]
        dlg = QRect(int(BASE_W*0.05), int(BASE_H*0.78), int(BASE_W*0.58), int(BASE_H*0.18))

        # frame + bg (modern rounded pill)
        bg = self._get_color("dialog_bg", "#121212")
        bdr = self._get_color("dialog_bdr", "#333333")
        bg.setAlpha(215)
        p.setPen(QPen(bdr, 2))
        p.setBrush(QBrush(bg))
        p.drawRoundedRect(dlg, 14, 14)
        # wrap & draw
        p.setPen(self._get_color("text", "#FFFFFF"))
        p.setFont(QFont(self.theme.get("font_dialog","Arial"), 18))
        fm = p.fontMetrics()
        words = str(text).split()
        lines, cur = [], ""
        maxw = max(0, dlg.width()-16)
        for w in words:
            t = (cur+" "+w).strip()
            if fm.horizontalAdvance(t) <= maxw:
                cur = t
            else:
                if cur: lines.append(cur)
                cur = w
        if cur: lines.append(cur)
        for i, ln in enumerate(lines[:3]):
            p.drawText(dlg.adjusted(16,12,-16,-12).translated(0, i*(fm.height()+6)), ln)
    
    def _draw_dialog_allies(self, p: QPainter):
        """Draw smaller health bars and status icons for allies during dialog mode."""
        allies = [c for c in self.combatants if (c.get("side") or "Enemy").lower() == "friendly"]
        if not allies:
            return
        
        # Small compact display at top-left during dialog
        start_x = int(BASE_W * 0.05)
        start_y = int(BASE_H * 0.05)
        card_w = 200
        card_h = 40
        gap = 6
        
        for i, ally in enumerate(allies[:5]):  # Max 5 allies shown
            y = start_y + i * (card_h + gap)
            card = QRect(start_x, y, card_w, card_h)
            
            # Background
            bg = self._get_color("friendly_bg", "#2A2A2A")
            bg.setAlpha(200)
            p.setBrush(QBrush(bg))
            p.setPen(QPen(self._get_color("friendly_text", "#77DD77"), 1))
            p.drawRoundedRect(card, 6, 6)
            
            # Name
            p.setPen(self._get_color("text", "#FFFFFF"))
            p.setFont(QFont(self.theme.get("font_combat_name", "Arial"), 11))
            p.drawText(card.adjusted(6, 4, -6, -20), Qt.AlignLeft | Qt.AlignTop, ally.get("name", "???"))
            
            # Small HP bar
            hp_max = max(1, int(ally.get("hpMax") or 1))
            hp = max(0, min(int(ally.get("hp") or 0), hp_max))
            ratio = hp / hp_max
            bar_w = card_w - 12
            bar_h = 8
            bar_x = card.x() + 6
            bar_y = card.y() + card_h - 14
            
            # Background bar
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(40, 40, 40, 180)))
            p.drawRoundedRect(QRect(bar_x, bar_y, bar_w, bar_h), 3, 3)
            # Filled portion
            fill_w = int(bar_w * ratio)
            if fill_w > 0:
                p.setBrush(QBrush(QColor(40, 200, 120, 220)))
                p.drawRoundedRect(QRect(bar_x, bar_y, fill_w, bar_h), 3, 3)
            
            # HP text
            p.setPen(self._get_color("text", "#FFFFFF"))
            p.setFont(QFont(self.theme.get("font_combat_hp", "Arial"), 9))
            p.drawText(bar_x, bar_y - 2, f"{hp}/{hp_max}")
            
            # Small status icons (right side)
            statuses = ally.get("statuses") or []
            icon_sz = 16
            sx = card.right() - icon_sz - 4
            sy = bar_y - 2
            for key in statuses[:3]:  # Max 3 status icons
                pix = self.status_icons.get(str(key).lower())
                if pix and not pix.isNull():
                    p.drawPixmap(QRect(sx, sy, icon_sz, icon_sz), pix)
                else:
                    p.setPen(Qt.NoPen)
                    p.setBrush(QBrush(QColor(200, 200, 200, 200)))
                    p.drawEllipse(QRect(sx, sy, icon_sz, icon_sz))
                sx -= icon_sz + 2
