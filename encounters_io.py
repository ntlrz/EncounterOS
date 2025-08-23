# encounters_io.py
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, Literal
from pathlib import Path
import json
from datetime import datetime, timezone

EncType = Literal["combat", "dialog"]

DATA_ROOT = Path("./data/encounters")
COMBAT_DIR = DATA_ROOT / "combat"
DIALOG_DIR = DATA_ROOT / "dialog"

def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

@dataclass
class CombatEntry:
    source_id: str
    count: int = 1

@dataclass
class CombatEncounter:
    encounter_id: str
    name: str
    type: EncType  # "combat"
    sides: Dict[str, List[CombatEntry]]  # {"allies":[...], "opponents":[...]}
    notes: str = ""
    created_at: str = ""

    def to_json(self) -> dict:
        d = asdict(self)
        # dataclasses → plain dicts
        d["sides"] = {
            "allies": [asdict(e) for e in self.sides.get("allies", [])],
            "opponents": [asdict(e) for e in self.sides.get("opponents", [])],
        }
        if not d.get("created_at"):
            d["created_at"] = _now_iso()
        return d

@dataclass
class DialogBlock:
    speaker: str = ""
    text: str = ""
    portrait: str = ""        # path to png/webp/jpg
    placement: str = "left"   # "left" | "right" | "center"

@dataclass
class DialogEncounter:
    encounter_id: str
    name: str
    type: EncType  # "dialog"
    sequence: List[DialogBlock]
    created_at: str = ""

    def to_json(self) -> dict:
        d = asdict(self)
        d["sequence"] = [asdict(b) for b in self.sequence]
        if not d.get("created_at"):
            d["created_at"] = _now_iso()
        return d

class EncounterStore:
    def __init__(self, root: Path = DATA_ROOT):
        self.root = root
        COMBAT_DIR.mkdir(parents=True, exist_ok=True)
        DIALOG_DIR.mkdir(parents=True, exist_ok=True)

    # ---- Save ----
    def save_combat(self, enc: CombatEncounter) -> Path:
        p = COMBAT_DIR / f"{enc.encounter_id}.json"
        p.write_text(json.dumps(enc.to_json(), indent=2), encoding="utf-8")
        return p

    def save_dialog(self, enc: DialogEncounter) -> Path:
        p = DIALOG_DIR / f"{enc.encounter_id}.json"
        p.write_text(json.dumps(enc.to_json(), indent=2), encoding="utf-8")
        return p

    # ---- List ----
    def list_combat(self) -> List[dict]:
        out = []
        for f in sorted(COMBAT_DIR.glob("*.json")):
            try:
                out.append(json.loads(f.read_text(encoding="utf-8")))
            except Exception:
                pass
        return out

    def list_dialog(self) -> List[dict]:
        out = []
        for f in sorted(DIALOG_DIR.glob("*.json")):
            try:
                out.append(json.loads(f.read_text(encoding="utf-8")))
            except Exception:
                pass
        return out

    # ---- Load ----
    def load_combat(self, encounter_id: str) -> Optional[dict]:
        p = COMBAT_DIR / f"{encounter_id}.json"
        if not p.exists(): return None
        return json.loads(p.read_text(encoding="utf-8"))

    def load_dialog(self, encounter_id: str) -> Optional[dict]:
        p = DIALOG_DIR / f"{encounter_id}.json"
        if not p.exists(): return None
        return json.loads(p.read_text(encoding="utf-8"))
