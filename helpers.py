import json
import os
import random
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, List, Dict, Optional, Tuple

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

@dataclass(frozen=True)
class JsonLoadResult:
    path: Path
    status: str
    data: Any = None
    error: str | None = None

    @property
    def valid(self) -> bool:
        return self.status == "valid"

    @property
    def missing(self) -> bool:
        return self.status == "missing"


def load_json(path: Path) -> JsonLoadResult:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return JsonLoadResult(path, "missing")
    except Exception as e:
        return JsonLoadResult(path, "invalid", error=str(e))
    try:
        return JsonLoadResult(path, "valid", data=json.loads(text))
    except Exception as e:
        return JsonLoadResult(path, "invalid", error=str(e))


def safe_json(path: Path, default):
    result = load_json(path)
    return result.data if result.valid else default


def config_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    return default


def config_choice(value: Any, choices, default: str) -> str:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in choices:
            return normalized
    return default


def atomic_write_bytes(path: Path, data: bytes):
    path = Path(path)
    fd, temp_name = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    except Exception:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8"):
    atomic_write_bytes(Path(path), text.encode(encoding))


def write_json(path: Path, data: Any):
    atomic_write_text(Path(path), json.dumps(data, indent=2), encoding="utf-8")


def write_dialog_txt(blocks: List[str]):
    text = "\n\n".join(b.strip() for b in blocks if b.strip())
    path = Path("dialog.txt")
    atomic_write_text(path, text, encoding="utf-8")

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


def roll_dice(formula: str) -> Tuple[int, str]:
    """Parse a formula like '1d20+5', '2d6', 'd20', '3d8-2' and return (total, breakdown_str)."""
    import re
    formula = (formula or "").strip().lower().replace(" ", "")
    if not formula:
        return 0, ""

    # Match one optional N, d, M, optional +X or -X
    m = re.match(r"^(\d*)d(\d+)([+-]\d+)?$", formula)
    if not m:
        return 0, f"Invalid formula: {formula}"

    n = int(m.group(1) or 1)
    faces = int(m.group(2))
    mod = int(m.group(3) or 0)

    if n < 1 or faces < 1:
        return 0, "Invalid formula"

    rolls = [random.randint(1, faces) for _ in range(n)]
    total = sum(rolls) + mod
    parts = "+".join(str(r) for r in rolls)
    if mod != 0:
        parts += f"{mod:+d}"
    breakdown = f"{formula} → {parts} = {total}"
    return total, breakdown


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
    base_dir = base_dir.resolve()

    def validated_members(zf: zipfile.ZipFile):
        members = []
        seen = set()
        reserved_names = {"CON", "PRN", "AUX", "NUL"}
        reserved_names.update(f"COM{i}" for i in range(1, 10))
        reserved_names.update(f"LPT{i}" for i in range(1, 10))
        for info in zf.infolist():
            raw_name = info.filename.replace("\\", "/")
            pure = PurePosixPath(raw_name)
            parts = pure.parts
            unsafe_windows_part = any(
                ":" in part
                or part.endswith((" ", "."))
                or part.split(".", 1)[0].upper() in reserved_names
                for part in parts
            )
            if (
                not raw_name
                or "\x00" in raw_name
                or pure.is_absolute()
                or not parts
                or any(part in ("", ".", "..") for part in parts)
                or unsafe_windows_part
            ):
                raise ValueError(f"Unsafe backup path: {info.filename}")
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise ValueError(f"Symbolic links are not allowed in backups: {info.filename}")
            rel = Path(*parts)
            dest = (base_dir / rel).resolve()
            try:
                dest.relative_to(base_dir)
            except ValueError:
                raise ValueError(f"Backup path escapes the application directory: {info.filename}")
            key = os.path.normcase(str(dest))
            if key in seen:
                raise ValueError(f"Duplicate backup destination: {info.filename}")
            seen.add(key)
            members.append((info, rel, dest))
        return members

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            members = validated_members(zf)
            for info, _, dest in members:
                if info.is_dir():
                    if dest.exists() and not dest.is_dir():
                        return False, f"Directory conflicts with an existing file: {info.filename}"
                else:
                    if dest.exists() and dest.is_dir():
                        return False, f"File conflicts with an existing directory: {info.filename}"
                    if not overwrite and dest.exists():
                        return False, f"File already exists: {info.filename}. Choose 'Overwrite' to replace."
                for parent in dest.parents:
                    if parent == base_dir.parent:
                        break
                    if parent.exists() and not parent.is_dir():
                        return False, f"Parent path is not a directory: {info.filename}"

            # Stage on the target filesystem so final replacements stay atomic.
            stage_parent = base_dir
            stage_root = Path(tempfile.mkdtemp(prefix=".encounteros-restore-", dir=str(stage_parent)))
            payload_root = stage_root / "payload"
            rollback_root = stage_root / "rollback"
            installed = []
            displaced = []
            created_dirs = []
            try:
                payload_root.mkdir()
                rollback_root.mkdir()
                for info, rel, _ in members:
                    staged = payload_root / rel
                    if info.is_dir():
                        staged.mkdir(parents=True, exist_ok=True)
                    else:
                        staged.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(info, "r") as source, staged.open("wb") as target:
                            shutil.copyfileobj(source, target)

                def ensure_directory(path: Path):
                    missing = []
                    current = path
                    while current != base_dir.parent and not current.exists():
                        missing.append(current)
                        current = current.parent
                    if current.exists() and not current.is_dir():
                        raise NotADirectoryError(str(current))
                    for directory in reversed(missing):
                        directory.mkdir()
                        created_dirs.append(directory)

                for info, _, dest in sorted(members, key=lambda item: len(item[1].parts)):
                    if info.is_dir():
                        ensure_directory(dest)
                        continue
                    ensure_directory(dest.parent)
                    staged = payload_root / Path(*PurePosixPath(info.filename.replace("\\", "/")).parts)
                    if dest.exists():
                        backup = rollback_root / str(len(displaced))
                        os.replace(dest, backup)
                        displaced.append((dest, backup))
                    os.replace(staged, dest)
                    installed.append(dest)
            except Exception:
                for dest in reversed(installed):
                    try:
                        dest.unlink()
                    except FileNotFoundError:
                        pass
                for dest, backup in reversed(displaced):
                    if backup.exists():
                        os.replace(backup, dest)
                for directory in reversed(created_dirs):
                    try:
                        directory.rmdir()
                    except OSError:
                        pass
                raise
            finally:
                shutil.rmtree(stage_root, ignore_errors=True)
        return True, ""
    except Exception as e:
        return False, str(e)
