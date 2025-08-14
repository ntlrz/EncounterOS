# migrate_party.py
import json, os

PARTY_FILE = "party.json"

def main():
    if not os.path.exists(PARTY_FILE):
        print("party.json not found.")
        return

    with open(PARTY_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    party = data.get("party", [])
    changed = False

    for m in party:
        if "initMod" not in m:
            m["initMod"] = 0
            changed = True
        if "initiative" not in m:
            m["initiative"] = None
            changed = True
        if "statusEffects" not in m:
            m["statusEffects"] = []
            changed = True

    if changed:
        with open(PARTY_FILE, "w", encoding="utf-8") as f:
            json.dump({"party": party}, f, indent=2)
        print("party.json updated.")
    else:
        print("party.json already up to date.")

if __name__ == "__main__":
    main()
