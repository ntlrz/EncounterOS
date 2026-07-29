import os
import sys
from pathlib import Path


def resolve_runtime_dirs(
    *,
    frozen: bool,
    executable: str | Path,
    module_file: str | Path,
    bundle_dir: str | Path | None = None,
) -> tuple[Path, Path]:
    """Resolve writable and bundled roots without consulting the CWD."""
    if frozen:
        base_dir = Path(executable).resolve().parent
        resource_dir = Path(bundle_dir or base_dir).resolve()
        return base_dir, resource_dir
    base_dir = Path(module_file).resolve().parent
    return base_dir, base_dir


_BASE_DIR, _RESOURCE_DIR = resolve_runtime_dirs(
    frozen=bool(getattr(sys, "frozen", False)),
    executable=sys.executable,
    module_file=__file__,
    bundle_dir=getattr(sys, "_MEIPASS", None),
)

APP_DIR = _BASE_DIR
RESOURCE_DIR = _RESOURCE_DIR
PARTY_FP = _BASE_DIR / "party.json"
CONFIG_FP = _BASE_DIR / "config.json"
DIALOG_FP = _BASE_DIR / "dialog.txt"
DIALOGMETA = _BASE_DIR / "dialog_meta.json"
DIALOG_BLOCKS = _BASE_DIR / "dialog_blocks.json"
THEMES_DIR = _RESOURCE_DIR / "themes"
STATUS_DIR = _RESOURCE_DIR / "icons" / "status"
DIALOG_PORTRAITS_DIR = _RESOURCE_DIR / "icons" / "dialog_portraits"

DATA_ROOT = _BASE_DIR / "data" / "encounters"
COMBAT_DIR = DATA_ROOT / "combat"
DIALOG_DIR = DATA_ROOT / "dialog"
COMBAT_DIR.mkdir(parents=True, exist_ok=True)
DIALOG_DIR.mkdir(parents=True, exist_ok=True)

ROSTERS_DIR = _BASE_DIR / "data" / "rosters"
ROSTERS_DIR.mkdir(parents=True, exist_ok=True)
SESSION_ROSTER_FP = ROSTERS_DIR / "_session.json"

LOG_DIR = _BASE_DIR / "data"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "session.log"
DICE_SESSION_FP = LOG_DIR / "dice_session.json"
VAULT_DIR = _BASE_DIR / "data" / "notes"
VAULT_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_NOTE = VAULT_DIR / "notes.md"

# For export/backup: directory to suggest for save, and backup zip name prefix
BACKUPS_DIR = _BASE_DIR / "backups"
BACKUPS_DIR.mkdir(parents=True, exist_ok=True)

# Frozen-runtime diagnostics belong in a stable per-user location even when the
# portable application directory is read-only or the process starts elsewhere.
LOCAL_APPDATA_DIR = Path(
    os.environ.get("LOCALAPPDATA")
    or (Path.home() / "AppData" / "Local")
)
OVERLAY_LOG_DIR = LOCAL_APPDATA_DIR / "EncounterOS" / "logs"
OVERLAY_LOG_FILE = OVERLAY_LOG_DIR / "overlay.log"
