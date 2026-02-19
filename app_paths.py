import sys
from pathlib import Path

# When run as PyInstaller .exe: writable paths next to the executable, resources inside bundle.
if getattr(sys, "frozen", False):
    _BASE_DIR = Path(sys.executable).resolve().parent
    _RESOURCE_DIR = Path(sys._MEIPASS)
else:
    _BASE_DIR = Path(__file__).resolve().parent
    _RESOURCE_DIR = _BASE_DIR

APP_DIR = _BASE_DIR
PARTY_FP = _BASE_DIR / "party.json"
CONFIG_FP = _BASE_DIR / "config.json"
DIALOG_FP = _BASE_DIR / "dialog.txt"
DIALOGMETA = _BASE_DIR / "dialog_meta.json"
DIALOG_BLOCKS = _BASE_DIR / "dialog_blocks.json"
THEMES_DIR = _RESOURCE_DIR / "themes"
STATUS_DIR = _RESOURCE_DIR / "icons" / "status"

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
VAULT_DIR = _BASE_DIR / "data" / "notes"
VAULT_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_NOTE = VAULT_DIR / "notes.md"

# For export/backup: directory to suggest for save, and backup zip name prefix
BACKUPS_DIR = _BASE_DIR / "backups"
BACKUPS_DIR.mkdir(parents=True, exist_ok=True)