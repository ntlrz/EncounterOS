# tracker_overlay.py — EncounterOS overlay HUD. Reads party/config/dialog + themes and paints HUD.
# Compatible with the GM UI posted (auto-refresh, theme hot-reload, enemy status icons).
import json, os, sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QRect, QSize, QPoint
from PySide6.QtGui import QPainter, QColor, QBrush, QPen, QFont, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

APP_DIR    = Path(__file__).resolve().parent
PARTY_FP   = APP_DIR/"party.json"
CONFIG_FP  = APP_DIR/"config.json"
DIALOG_FP  = APP_DIR/"dialog.txt"
DIALOGMETA = APP_DIR/"dialog_meta.json"
THEMES_DIR = APP_DIR/"themes"
STATUS_DIR = APP_DIR/"icons"/"status"

BASE_W, BASE_H = 1280, 720
ICON_SIZE      = QSize(64,64)
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
    else:  # "stretch"
        return (sx, sy, 0.0, 0.0)

# -------- Theme manager --------
class ThemeManager:
    def __init__(self):
        self.grid = {
            "grid": {"cols":24,"rows":24,"margin":8,"gutter":8},
            "regions": {
                "right_column": {"gridRect":[16, 2, 8, 20]},
                "dialog_box":   {"gridRect":[1, 20, 14, 3]},
            }
        }
        self.colors = {
            "card_bg":       "#000000",
            "border_idle":   "#C8C8C8",
            "border_active": "#FFD864",
            "text":          "#FFFFFF",
            "hp_good":       "#32C864",
            "hp_back":       "#C83232",
            "dialog_bg":     "#000000",
            "dialog_border": "#C8C8C8",
        }
        self.fonts = {
            "base_family": "Consolas",
            "base_size":   12,
            "dialog_size": 14,
            "small_size":  10
        }

    def _parse_hex(self, s, fallback):
        try:
            if not isinstance(s, str): return QColor(fallback)
            s = s.strip()
            if not s.startswith("#"): s = "#" + s
            qc = QColor(s); return qc if qc.isValid() else QColor(fallback)
        except:
            return QColor(fallback)

    def load_theme(self, theme_name: str | None):
        # reset to defaults first (so missing keys fall back)
        self.__init__()
        if not theme_name:
            return
        tdir = THEMES_DIR / theme_name
        tjson = tdir / "theme.json"
        if not tjson.exists():
            return
        try:
            data = json.loads(tjson.read_text(encoding="utf-8"))

            layout = data.get("layout", {})
            grid = layout.get("grid", {})
            self.grid["grid"].update(grid)
            regions = layout.get("regions", {})
            if regions:
                self.grid["regions"].update(regions)

            vars_data = data.get("vars", {})
            col = vars_data.get("colors", {})
            for k in self.colors.keys():
                if k in col: self.colors[k] = col[k]

            f = vars_data.get("fonts", {})
            self.fonts["base_family"] = f.get("base_family", self.fonts["base_family"])
            self.fonts["base_size"]   = int(f.get("base_size",   self.fonts["base_size"]))
            self.fonts["dialog_size"] = int(f.get("dialog_size", self.fonts["dialog_size"]))
            self.fonts["small_size"]  = int(f.get("small_size",  self.fonts["small_size"]))
        except Exception:
            # swallow theme parse errors, keep defaults
            pass

    def qcolor(self, key, fallback="#FFFFFF"):
        return self._parse_hex(self.colors.get(key, fallback), fallback)

    def region_rect(self, size, region_id)->QRect:
        g=self.grid["grid"]
        r = self.grid["regions"].get(region_id, {"gridRect":[0,0,g['cols'],g['rows']]})["gridRect"]
        cols,rows,margin,gutter = g["cols"],g["rows"],g["margin"],g["gutter"]
        x,y,w,h = r
        cell_w = (size.width()-2*margin - gutter*(cols-1))/cols
        cell_h = (size.height()-2*margin - gutter*(rows-1))/rows
        px = round(margin + x*(cell_w+gutter))
        py = round(margin + y*(cell_h+gutter))
        pw = round(w*cell_w + (w-1)*gutter)
        ph = round(h*cell_h + (h-1)*gutter)
        return QRect(px,py,pw,ph)

# -------- helpers --------
def safe_json(path:Path, default):
    try: return json.loads(path.read_text(encoding="utf-8"))
    except: return default

def load_dialog_blocks(path:Path):
    out=[]
    try:
        block=[]
        for line in path.read_text(encoding="utf-8").splitlines():
            s=line.strip()
            if s=="":
                if block: out.append(" ".join(block)); block=[]
            else: block.append(s)
        if block: out.append(" ".join(block))
    except: pass
    return out

def load_icon(rel_path:str)->QPixmap|None:
    if not rel_path: return None
    p=(APP_DIR/rel_path).resolve()
    if not p.exists(): return None
    pm=QPixmap(str(p))
    if pm.isNull(): return None
    return pm.scaled(ICON_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation)

def load_status_icons()->dict:
    cache={}
    if not STATUS_DIR.exists(): return cache
    for fn in os.listdir(STATUS_DIR):
        if fn.lower().endswith(".png"):
            pm=QPixmap(str(STATUS_DIR/fn))
            if not pm.isNull():
                cache[os.path.splitext(fn)[0].lower()] = pm.scaled(STATUS_ICON_SZ, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return cache

# -------- Overlay widget --------
class Overlay(QWidget):
    def __init__(self, debug=False):
        super().__init__()
        self.setWindowTitle("EncounterOS Overlay")
        self.resize(BASE_W, BASE_H)

        # Window-capture friendly
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.setMouseTracking(True)

        # simple drag to move
        self._drag_pos: QPoint | None = None

        cfg0 = safe_json(CONFIG_FP, {"theme":"gm-modern"})
        self.theme = ThemeManager()
        self.current_theme = cfg0.get("theme", "gm-modern")
        self.theme.load_theme(self.current_theme)

        # live data
        self.party  = safe_json(PARTY_FP, {"party":[]})
        self.dialog = load_dialog_blocks(DIALOG_FP)
        self.dialog_meta = safe_json(DIALOGMETA, {})
        self.config = safe_json(CONFIG_FP, {"combat_mode":False,"turnIndex":0,"dialogIndex":0,"theme":self.current_theme})

        self.status_icons = load_status_icons()
        self._cache_icons = {}
        self._portrait_cache = {}

        self._mtimes = {
            "party":  self.mtime(PARTY_FP),
            "config": self.mtime(CONFIG_FP),
            "dialog": self.mtime(DIALOG_FP),
            "meta":   self.mtime(DIALOGMETA),
            "status": self.mtime_dir(STATUS_DIR),
            "theme_dir": self.mtime_dir(THEMES_DIR / self.current_theme),
        }

        # Auto-refresh settings from config
        self.auto_refresh = bool(self.config.get("auto_refresh", True))
        self.poll_ms = max(100, int(self.config.get("poll_ms", 200)))

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll_files)
        if self.auto_refresh:
            self.timer.start(self.poll_ms)

    def set_fit_mode(self, mode: str):
        mode = (mode or "contain").strip().lower()
        if mode not in ("contain","cover","stretch"): mode = "contain"
        self._fit_mode = mode
        self.update()

    def move_to_screen(self, screen_name: str | None):
        app = QApplication.instance()
        scr = None
        if screen_name:
            for s in app.screens():
                if screen_name.lower() in s.name().lower():
                    scr = s; break
        if scr is None:
            scr = app.primaryScreen()
        geo = scr.geometry()
        if self.isFullScreen():
            # ensure full coverage on that screen
            self.setGeometry(geo)
        else:
            # center a 1280x720 window on that screen
            x = geo.x() + (geo.width() - BASE_W)//2
            y = geo.y() + (geo.height() - BASE_H)//2
            self.setGeometry(x, y, BASE_W, BASE_H)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_F11:
            if self.isFullScreen():
                self.showNormal()
            else:
                self.showFullScreen()
        else:
            super().keyPressEvent(e)


    # --- drag to move ---
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag_pos is not None and (e.buttons() & Qt.LeftButton):
            self.move(e.globalPosition().toPoint() - self._drag_pos)
            e.accept()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = None
            e.accept()

    # --- file mtimes helpers ---
    def mtime(self, p:Path)->float: return p.stat().st_mtime if p.exists() else 0.0
    def mtime_dir(self, d:Path)->float:
        if not d.exists(): return 0.0
        try: return max(((d/f).stat().st_mtime for f in os.listdir(d)), default=0.0)
        except: return 0.0

    def poll_files(self):
        mt_p = self.mtime(PARTY_FP)
        mt_c = self.mtime(CONFIG_FP)
        mt_d = self.mtime(DIALOG_FP)
        mt_m = self.mtime(DIALOGMETA)
        mt_s = self.mtime_dir(STATUS_DIR)
        mt_t = self.mtime_dir(THEMES_DIR / self.current_theme)

        if mt_p != self._mtimes["party"]:
            self.party = safe_json(PARTY_FP, {"party":[]}); self._cache_icons.clear()
            self._mtimes["party"] = mt_p

        if mt_c != self._mtimes["config"]:
            self.config = safe_json(CONFIG_FP, self.config or {})
            self._mtimes["config"] = mt_c
            # theme changed?
            new_theme = self.config.get("theme", self.current_theme)
            if new_theme != self.current_theme:
                self.current_theme = new_theme
                self.theme.load_theme(self.current_theme)
                # reset theme dir watch
                self._mtimes["theme_dir"] = self.mtime_dir(THEMES_DIR / self.current_theme)
            # auto-refresh/interval changed?
            self.auto_refresh = bool(self.config.get("auto_refresh", True))
            self.poll_ms = max(100, int(self.config.get("poll_ms", 200)))
            if self.auto_refresh and not self.timer.isActive():
                self.timer.start(self.poll_ms)
            elif not self.auto_refresh and self.timer.isActive():
                self.timer.stop()
            elif self.timer.isActive() and self.timer.interval() != self.poll_ms:
                self.timer.start(self.poll_ms)

        if mt_d != self._mtimes["dialog"]:
            self.dialog = load_dialog_blocks(DIALOG_FP)
            self._mtimes["dialog"] = mt_d

        if mt_m != self._mtimes["meta"]:
            self.dialog_meta = safe_json(DIALOGMETA, {})
            self._portrait_cache.clear()
            self._mtimes["meta"] = mt_m

        if mt_s != self._mtimes["status"]:
            self.status_icons = load_status_icons()
            self._mtimes["status"] = mt_s

        if mt_t != self._mtimes["theme_dir"]:
            # live theme editing
            self.theme.load_theme(self.current_theme)
            self._mtimes["theme_dir"] = mt_t

        self.update()

    # ---------- paint ----------
    def paintEvent(self, ev):
        p = QPainter(self)

        # Clear fully transparent
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.fillRect(self.rect(), Qt.transparent)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)

        mode = getattr(self, "_fit_mode", "contain")
        sx, sy, ox, oy = _compute_fit(BASE_W, BASE_H, self.width(), self.height(), mode)
        p.translate(ox, oy)
        p.scale(sx, sy)

        # theme colors & fonts
        col_card_bg     = self.theme.qcolor("card_bg", "#000000")
        col_border_idle = self.theme.qcolor("border_idle", "#C8C8C8")
        col_border_act  = self.theme.qcolor("border_active", "#FFD864")
        col_text        = self.theme.qcolor("text", "#FFFFFF")
        col_hp_good     = self.theme.qcolor("hp_good", "#32C864")
        col_hp_back     = self.theme.qcolor("hp_back", "#C83232")
        col_dialog_bg   = self.theme.qcolor("dialog_bg", "#000000")
        col_dialog_bdr  = self.theme.qcolor("dialog_border", "#C8C8C8")

        base_family = self.theme.fonts["base_family"]
        font_base   = QFont(base_family, self.theme.fonts["base_size"])
        font_small  = QFont(base_family, self.theme.fonts["small_size"])
        font_dialog = QFont(base_family, self.theme.fonts["dialog_size"])

        p.setFont(font_base)

        combat = bool(self.config.get("combat_mode", False))
        full_party = self.party.get("party", [])
        turn_idx = max(0, min(self.config.get("turnIndex",0), max(0,len(full_party)-1)))

        logical_size = QSize(BASE_W, BASE_H)
        right_rect = self.theme.region_rect(logical_size, "right_column")
        dialog_rect= self.theme.region_rect(logical_size, "dialog_box")

        render_party = full_party if combat else [m for m in full_party if not m.get("isEnemy",False)]

        # header (combat only)
        if combat and full_party:
            active_name = full_party[turn_idx]["name"] if 0<=turn_idx<len(full_party) else ""
            p.setPen(col_text); p.drawText(20, 28, f"Turn {turn_idx+1}/{len(full_party)}: {active_name}")

        # party/enemy cards
        box_w = right_rect.width()
        box_h = 100
        margin = 10
        total_h = len(render_party)*(box_h+margin)
        start_y = right_rect.y() + max(0, (right_rect.height()-total_h)//2)

        for i, m in enumerate(render_party):
            y = start_y + i*(box_h+margin)
            card = QRect(right_rect.x(), y, box_w, box_h)
            is_active = (combat and 0<=turn_idx<len(full_party) and full_party[turn_idx]["name"]==m["name"])

            p.fillRect(card, col_card_bg)
            pen = QPen(col_border_act if is_active else col_border_idle); pen.setWidth(3); p.setPen(pen); p.drawRect(card)

            px = card.x()+10; py = card.y() + (box_h - ICON_SIZE.height())//2
            frame = QRect(px-2, py-2, ICON_SIZE.width()+4, ICON_SIZE.height()+4)
            p.fillRect(frame, QColor(0,0,0,120)); p.setPen(col_border_idle); p.drawRect(frame)

            name = m.get("name","")
            icon = getattr(self, "_cache_icons", {}).get(name)
            if icon is None:
                icon = load_icon(m.get("icon","")); self._cache_icons[name] = icon
            if icon: p.drawPixmap(px, py, icon)

            content_x = px + ICON_SIZE.width() + 12
            p.setPen(col_text); p.setFont(font_base); p.drawText(content_x, card.y()+20, name)

            if not m.get("isEnemy", False):
                maxhp = max(1, int(m.get("maxHP",1))); curhp = max(0, min(int(m.get("currentHP",0)), maxhp))
                ratio = curhp/maxhp
                bar_x = content_x; bar_y = card.y()+40; bar_w = card.right() - bar_x - 10; bar_h = 18
                p.fillRect(QRect(bar_x,bar_y,bar_w,bar_h), col_hp_back)
                p.fillRect(QRect(bar_x,bar_y,int(bar_w*ratio),bar_h), col_hp_good)

                statuses = [s.lower().replace(" ","_") for s in (m.get("statusEffects",[]) or []) if isinstance(s,str)]
                sx = bar_x + bar_w - STATUS_ICON_SZ.width() - 4
                sy = bar_y + (bar_h - STATUS_ICON_SZ.height())//2
                for key in statuses[:4]:
                    pix = self.status_icons.get(key)
                    if pix:
                        p.drawPixmap(sx, sy, pix)
                    else:
                        r=STATUS_ICON_SZ.width()//2
                        p.setPen(QPen(QColor(0,0,0))); p.setBrush(QBrush(col_border_idle)); p.drawEllipse(sx, sy, 2*r, 2*r)
                        p.setPen(QPen(QColor(0,0,0))); p.setFont(font_small)
                        p.drawText(QRect(sx, sy, 2*r, 2*r), Qt.AlignCenter, key[:1].upper())
                    sx -= STATUS_ICON_SZ.width() + 4

                p.setPen(col_text)
                fm = p.fontMetrics()
                hp_text = f"{curhp}/{maxhp} HP"
                p.drawText(bar_x+6, bar_y + bar_h + fm.ascent() + 4, hp_text)
            else:
                if combat:
                    maxhp=max(1,int(m.get("maxHP",1))); curhp=max(0,min(int(m.get("currentHP",0)),maxhp))
                    pct=curhp/maxhp if maxhp else 0
                    if curhp<=0: status="Defeated"
                    elif pct>=0.90: status="Healthy"
                    elif pct>=0.70: status="Scratched"
                    elif pct>=0.40: status="Bruised"
                    elif pct>=0.10: status="Wounded"
                    else: status="Critical"
                    p.setPen(col_text); p.drawText(content_x, card.y()+54, f"Status: {status}")

                    # --- Enemy status icons (even without HP bar) ---
                    statuses = [s.lower().replace(" ","_") for s in (m.get("statusEffects",[]) or []) if isinstance(s,str)]
                    if statuses:
                        sx = content_x
                        sy = card.y() + 72
                        for key in statuses[:6]:
                            pix = self.status_icons.get(key)
                            if pix:
                                p.drawPixmap(sx, sy, pix)
                                sx += STATUS_ICON_SZ.width() + 4
                            else:
                                r=STATUS_ICON_SZ.width()//2
                                p.setPen(QPen(QColor(0,0,0))); p.setBrush(QBrush(col_border_idle)); p.drawEllipse(sx, sy, 2*r, 2*r)
                                p.setPen(QPen(QColor(0,0,0))); p.setFont(font_small)
                                p.drawText(QRect(sx, sy, 2*r, 2*r), Qt.AlignCenter, key[:1].upper())
                                sx += STATUS_ICON_SZ.width() + 4

        # ---- Persona-style dialog ----
        if not combat and self.dialog:
            dlg = self.theme.region_rect(self.size(), "dialog_box").intersected(self.rect())

            # 1) Draw PORTRAIT first (so the dialog panel overlaps it)
            idx = min(self.config.get("dialogIndex", 0), max(0, len(self.dialog) - 1))
            meta = self.dialog_meta.get(str(idx), {}) if isinstance(self.dialog_meta, dict) else {}
            portrait_rel = meta.get("portrait", "")
            if portrait_rel:
                path = (APP_DIR / portrait_rel).resolve()
                if path.exists():
                    raw = QPixmap(str(path))
                    if not raw.isNull():
                        # Inputs / defaults
                        req_scale = float(meta.get("portrait_scale", 1.0))
                        side   = str(meta.get("portrait_side", "left")).lower()     # 'left' | 'right'
                        anchor = str(meta.get("portrait_anchor", "bottom")).lower() # 'bottom'|'top'|'center'
                        pad_x  = int(meta.get("portrait_pad_x", 20))
                        pad_y  = int(meta.get("portrait_pad_y", -12))
                        top_margin = int(meta.get("portrait_top_margin", 8))        # prevent clipping at window top

                        # Base scaled portrait (requested scale first)
                        pm = raw.scaled(int(raw.width() * req_scale),
                                        int(raw.height() * req_scale),
                                        Qt.KeepAspectRatio, Qt.SmoothTransformation)

                        # Compute target X based on side
                        if side == "right":
                            x = dlg.right() - pad_x - pm.width()
                        else:
                            x = dlg.x() + pad_x

                        # Compute target Y based on anchor
                        if anchor == "bottom":
                            y = dlg.bottom() - pm.height() + pad_y
                        elif anchor == "top":
                            y = dlg.y() + pad_y
                        else:  # 'center'
                            y = dlg.center().y() - pm.height() // 2 + pad_y

                        # ---- AUTO-FIT: prevent top clipping by scaling down if needed ----
                        available_h = max(1, dlg.bottom() - top_margin + pad_y)
                        if anchor == "bottom":
                            if pm.height() > available_h:
                                scale_fit = available_h / float(pm.height())
                                if scale_fit < 1.0:
                                    new_w = max(1, int(pm.width() * scale_fit))
                                    new_h = max(1, int(pm.height() * scale_fit))
                                    pm = pm.scaled(new_w, new_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                                    y = dlg.bottom() - pm.height() + pad_y

                        # Final clamp: never draw above the top margin
                        if y < top_margin:
                            y = top_margin

                        p.drawPixmap(x, y, pm)



            # 2) Draw DIALOG PANEL AFTER portrait so panel overlaps the portrait’s bottom
            p.fillRect(dlg, col_dialog_bg)
            p.setPen(col_dialog_bdr)
            p.drawRect(dlg)
            p.setPen(self.theme.qcolor("text", "#FFFFFF"))
            p.setFont(font_dialog)

            text = self.dialog[idx]
            words = text.split()
            lines = []
            cur = ""
            fm = p.fontMetrics()
            maxw = max(0, dlg.width() - 16)
            for w in words:
                t = (cur + " " + w).strip()
                if fm.horizontalAdvance(t) <= maxw:
                    cur = t
                else:
                    if cur:
                        lines.append(cur)
                    cur = w
            if cur:
                lines.append(cur)
            for i, ln in enumerate(lines[:2]):
                p.drawText(dlg.adjusted(8, 8, -8, -8).translated(0, i * (fm.height() + 4)), ln)


def main():
    app = QApplication(sys.argv)
    w = Overlay(debug="--debug" in sys.argv)
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
