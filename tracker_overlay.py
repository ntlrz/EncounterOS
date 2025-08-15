import json, os, sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QRect, QSize
from PySide6.QtGui import QPainter, QColor, QBrush, QPen, QFont, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

APP_DIR    = Path(__file__).resolve().parent
PARTY_FP   = APP_DIR/"party.json"
CONFIG_FP  = APP_DIR/"config.json"
DIALOG_FP  = APP_DIR/"dialog.txt"
DIALOGMETA = APP_DIR/"dialog_meta.json"    # NEW: holds portrait + offsets per block
THEMES_DIR = APP_DIR/"themes"
STATUS_DIR = APP_DIR/"icons"/"status"

BASE_W, BASE_H = 1280, 720
ICON_SIZE      = QSize(64,64)
STATUS_ICON_SZ = QSize(24,24)

MAGENTA = QColor(255,0,255)
BLACK   = QColor(0,0,0)
WHITE   = QColor(255,255,255)

# -------- Theme manager (overlay only) --------
class ThemeManager:
    """
    Overlay Theme Manager
      - Reads layout.grid and layout.regions from theme.json
      - Reads vars.colors (hex) and vars.fonts to style the overlay paint
    """
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
            qc = QColor(s)
            return qc if qc.isValid() else QColor(fallback)
        except:
            return QColor(fallback)

    def load_theme(self, theme_name: str | None):
        self.__init__()  # reset defaults
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
        self.setWindowTitle("Party Tracker Overlay")
        self.resize(BASE_W, BASE_H)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.debug = debug

        cfg0 = safe_json(CONFIG_FP, {"theme":"gm-modern"})
        self.theme = ThemeManager()
        self.current_theme = cfg0.get("theme", "gm-modern")
        self.theme.load_theme(self.current_theme)

        self.party  = safe_json(PARTY_FP, {"party":[]})
        self.config = safe_json(CONFIG_FP, {"combat_mode":False,"turnIndex":0,"dialogIndex":0,"theme":self.current_theme})
        self.dialog = load_dialog_blocks(DIALOG_FP)
        self.dialog_meta = safe_json(DIALOGMETA, {})  # NEW
        self.status_icons = load_status_icons()
        self._cache_icons = {}
        self._portrait_cache = {}

        self._mtimes = {
            "party": self.mtime(PARTY_FP),
            "config": self.mtime(CONFIG_FP),
            "dialog": self.mtime(DIALOG_FP),
            "meta":   self.mtime(DIALOGMETA),
            "status": self.mtime_dir(STATUS_DIR),
            "theme":  self.current_theme
        }

        self.timer = QTimer(self); self.timer.timeout.connect(self.poll_files); self.timer.start(200)

    def mtime(self, p:Path)->float: return p.stat().st_mtime if p.exists() else 0.0
    def mtime_dir(self, d:Path)->float:
        if not d.exists(): return 0.0
        try: return max(( (d/f).stat().st_mtime for f in os.listdir(d) ), default=0.0)
        except: return 0.0

    def poll_files(self):
        mt_p = self.mtime(PARTY_FP)
        mt_c = self.mtime(CONFIG_FP)
        mt_d = self.mtime(DIALOG_FP)
        mt_m = self.mtime(DIALOGMETA)
        mt_s = self.mtime_dir(STATUS_DIR)

        if mt_p != self._mtimes["party"]:
            self.party  = safe_json(PARTY_FP, {"party":[]}); self._cache_icons.clear()
            self._mtimes["party"] = mt_p

        if mt_c != self._mtimes["config"]:
            self.config = safe_json(CONFIG_FP, {"combat_mode":False,"turnIndex":0,"dialogIndex":0,"theme":self.current_theme})
            self._mtimes["config"] = mt_c
            new_theme = self.config.get("theme", self.current_theme)
            if new_theme != self.current_theme:
                self.current_theme = new_theme
                self.theme.load_theme(self.current_theme)
                self.update()

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

        self.update()

    # ---------- paint ----------
    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), MAGENTA)  # chroma

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

        right_rect = self.theme.region_rect(self.size(), "right_column")
        dialog_rect= self.theme.region_rect(self.size(), "dialog_box")

        render_party = full_party if combat else [m for m in full_party if not m.get("isEnemy",False)]

        # header (combat only)
        if combat and full_party:
            active_name = full_party[turn_idx]["name"] if 0<=turn_idx<len(full_party) else ""
            p.setPen(col_text); p.drawText(20, 28, f"Turn {turn_idx+1}/{len(full_party)}: {active_name}")

        # party cards
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
                        letter = key[:1].upper()
                        p.drawText(QRect(sx, sy, 2*r, 2*r), Qt.AlignCenter, letter)
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

            if is_active:
                badge = QRect(card.right()-28, card.y()+8, 20, 20)
                p.fillRect(badge, self.theme.qcolor("border_active", "#FFD864"))
                p.setPen(QPen(QColor(0,0,0))); p.drawRect(badge)
                p.drawText(badge, Qt.AlignCenter, str(self.config.get("turnIndex",0)+1))

        # ---- Persona-style dialog ----
        if not combat and self.dialog:
            dlg = self.theme.region_rect(self.size(), "dialog_box").intersected(self.rect())

            # draw portrait FIRST (behind the box and text)
            idx = min(self.config.get("dialogIndex",0), max(0,len(self.dialog)-1))
            meta = self.dialog_meta.get(str(idx), {}) if isinstance(self.dialog_meta, dict) else {}
            portrait_rel = meta.get("portrait", "")
            if portrait_rel:
                path = (APP_DIR/portrait_rel).resolve()
                if path.exists():
                    key = (str(path), float(meta.get("portrait_scale", 1.0)))
                    pm = self._portrait_cache.get(key)
                    if pm is None:
                        raw = QPixmap(str(path))
                        scale = float(meta.get("portrait_scale", 1.0))
                        base_w, base_h = 360, 460
                        pm = raw.scaled(int(base_w*scale), int(base_h*scale), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                        self._portrait_cache[key] = pm
                    off_x = int(meta.get("portrait_offset_x", 20))
                    off_y = int(meta.get("portrait_offset_y", -120))
                    x = dlg.x() + off_x
                    y = dlg.y() - pm.height() + off_y
                    p.drawPixmap(x, y, pm)

            # box + text OVER portrait
            p.fillRect(dlg, col_dialog_bg); p.setPen(col_dialog_bdr); p.drawRect(dlg)
            p.setPen(col_text); p.setFont(font_dialog)

            text = self.dialog[idx]
            words=text.split(); lines=[]; cur=""
            fm = p.fontMetrics()
            maxw = max(0, dlg.width()-16)
            for w in words:
                t = (cur+" "+w).strip()
                if fm.horizontalAdvance(t) <= maxw: cur=t
                else:
                    if cur: lines.append(cur)
                    cur=w
            if cur: lines.append(cur)
            for i,ln in enumerate(lines[:2]):
                p.drawText(dlg.adjusted(8,8,-8,-8).translated(0, i*(fm.height()+4)), ln)

def main():
    app = QApplication(sys.argv)
    debug = ("--debug" in sys.argv)
    w = Overlay(debug=debug); w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
