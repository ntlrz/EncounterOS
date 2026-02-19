import json
import os
import random
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional, Tuple

try:
    import markdown as _MD_LIB  # pip install markdown
    _HAS_PY_MARKDOWN = True
except Exception:
    _MD_LIB = None
    _HAS_PY_MARKDOWN = False


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

def slug(s: str) -> str:
    return "-".join((s or "").strip().lower().split())

def safe_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def write_json(path: Path, data: dict):
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

def write_dialog_txt(blocks: List[str]):
    text = "\n\n".join(b.strip() for b in blocks if b.strip())
    path = Path("dialog.txt")
    path.write_text(text, encoding="utf-8")

def collect_suffixes(base_name: str, names: List[str]) -> set:
    base = base_name.strip()
    out = set()
    for n in names:
        if n == base:
            out.add("")
        if n.startswith(base + " "):
            tail = n[len(base)+1:].strip()
            if tail:
                out.add(tail)
    return out

def next_suffix(not_in: set) -> str:
    for i in range(26):
        s = chr(65+i)
        if s not in not_in:
            return s
    k = 1
    while True:
        s = f"A{k}"
        if s not in not_in:
            return s
        k += 1

def parse_rank(value) -> Tuple[float, str]:
    if value is None:
        return 0.0, "0"
    if isinstance(value, (int, float)):
        v = float(value)
        txt = str(int(v)) if v.is_integer() else str(v)
        return v, txt
    s = str(value).strip()
    if not s:
        return 0.0, "0"
    if "/" in s:
        try:
            num, den = s.split("/", 1)
            v = float(num) / float(den)
            return v, s
        except Exception:
            pass
    try:
        v = float(s)
        txt = str(int(v)) if float(v).is_integer() else s
        return v, txt
    except Exception:
        return 0.0, s

_RANK_LABEL_MAP = {
    "5e": "CR", "2024srd": "CR", "pf2e": "Level", "osr": "HD",
    "swade": "Rank", "gurps": "Points", "custom": "Rank",
}

def rank_label_for_pack(system: str | None, pack_rank_label: str | None) -> str:
    if pack_rank_label and str(pack_rank_label).strip():
        return str(pack_rank_label).strip()
    if system:
        return _RANK_LABEL_MAP.get(str(system).strip().lower(), "Rank")
    return "Rank"

def roll_d20() -> int:
    return random.randint(1, 20)

def load_status_catalog() -> list[str]:
    """Read status icon names from icons/status/*.png and return a sorted list."""
    from app_paths import STATUS_DIR
    names = []
    try:
        if STATUS_DIR.exists():
            for fn in os.listdir(STATUS_DIR):
                if fn.lower().endswith(".png"):
                    names.append(os.path.splitext(fn)[0])
    except Exception:
        pass
    if not names:
        # Fallback defaults if no icons found
        names = [
            "Poisoned","Stunned","Prone","Blessed","Charmed",
            "Grappled","Frightened","Invisible"
        ]
    # Deduplicate and sort case-insensitively
    return sorted({n for n in names}, key=str.lower)


def export_backup(base_dir: Path, dest_zip: Optional[Path] = None, include_data: bool = True) -> Path:
    """Create a timestamped zip of config, party, dialog, and optionally data/. Returns path to created zip."""
    from app_paths import (
        BACKUPS_DIR, PARTY_FP, CONFIG_FP, DIALOG_FP, DIALOGMETA, DIALOG_BLOCKS,
        ROSTERS_DIR, VAULT_DIR, LOG_DIR, DATA_ROOT, COMBAT_DIR, DIALOG_DIR,
    )
    if dest_zip is None:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
        dest_zip = BACKUPS_DIR / f"encounteros-backup-{timestamp}.zip"
    dest_zip = Path(dest_zip)
    to_add: List[Tuple[Path, str]] = []
    # Single files (relative to base_dir)
    for fp in (PARTY_FP, CONFIG_FP, DIALOG_FP, DIALOGMETA, DIALOG_BLOCKS):
        if fp.exists():
            to_add.append((fp, fp.name))
    # data/ subdirs
    if include_data:
        for folder in (ROSTERS_DIR, VAULT_DIR, COMBAT_DIR, DIALOG_DIR):
            if folder.exists():
                for f in folder.rglob("*"):
                    if f.is_file():
                        try:
                            rel = f.relative_to(base_dir)
                            to_add.append((f, str(rel).replace("\\", "/")))
                        except ValueError:
                            pass
        if LOG_DIR.exists():
            log_file = LOG_DIR / "session.log"
            if log_file.exists():
                to_add.append((log_file, "data/session.log"))
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for src, arcname in to_add:
            zf.write(src, arcname)
    return dest_zip


def restore_backup(zip_path: Path, base_dir: Path, overwrite: bool = False) -> Tuple[bool, str]:
    """Extract a backup zip into base_dir. If overwrite is False, returns (False, message) on existing files.
    Returns (True, '') on success, (False, error_message) on failure."""
    zip_path = Path(zip_path)
    base_dir = Path(base_dir)
    if not zip_path.exists():
        return False, "Backup file not found."
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for info in zf.infolist():
                dest = base_dir / info.filename
                if not overwrite and dest.exists() and not info.is_dir():
                    return False, f"File already exists: {info.filename}. Choose 'Overwrite' to replace."
                if info.is_dir():
                    dest.mkdir(parents=True, exist_ok=True)
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(zf.read(info))
        return True, ""
    except Exception as e:
        return False, str(e)