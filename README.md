# EncounterOS
**GM Control Center for TTRPGs** — track health, turns, dialogue, and party states with a stream‑friendly overlay.

---

## Overview
EncounterOS is a lightweight tool pairing a **Game Master UI** (GM UI) with a **player‑facing overlay** for OBS.  
The GM UI manages party data, combat, and dialogue; the overlay renders clean visuals ready to entice your players and viewers
into keeping up with the battle state.

---

## Features

### GM UI (Control Panel)

MVP Panel (always visible):
Add / edit / duplicate / remove combatants (allies & enemies) with optional portraits.
HP tracking: quick ±1/±5 and Set‑exact.
Status effects editor (checklist popup).
Initiative order & round tracker.
Advance / Previous turn (F5 / F7).
Peace ↔ Combat toggle.

Dialog Controls:
Create blocks with speaker, text, and optional portrait path.
Edit without sending live; Make Current (or F8) pushes block to overlay.
Prep multiple blocks in advance.

Rosters:
Load multiple different JSON packs of characters that can be send directly to dialog or combat controls
System-agnostic tag and rank system in place to easily sort between 

Encounters:
Save/load combat encounters and dialog sequences (JSON).
Send saved encounters directly into Combat or Dialog queues.

Log:
Records HP/status changes, turn advances, and encounter saves/loads/sends.

Notes:
Markdown scratchpad with live preview.
Multiple files in /data/notes/, switchable from a dropdown.
Autosaves while you type.

Timer:
Countdown and Stopwatch modes available currently.

### Overlay (Player View)
Transparent window (captured via OBS Window Capture).
Right‑column character cards:
Allies: portrait, HP bar, status icons.
Enemies: condition text + status icons (no HP bars).
Peace mode → shows allies only.
Combat mode → shows allies + enemies; highlights current turn.

### Themes
Themes live in themes/<theme-name>/theme.json and define:
Grid/layout regions (e.g., right column, dialog box)
Colors (cards, text, borders, HP bars)
Fonts and sizes
Switch themes from Overlay → Theme (menu). The choice is saved to config.json and reloaded live by the overlay.

---

## Hotkeys

Default mapping:
F4 → Toggle overlay on/off

F5 → Advance turn / dialog

F7 → Previous turn / dialog

F6 → Toggle Peace/Combat mode

F8 → Make selected dialog block live

Delete → Remove selected combatant or dialog block

/ → Focus quick‑add search

Double‑click a combatant → open editor

---

## File Structure
├── icons

│   ├── /status/

│   └── /dialog-portraits/

├── data

│   ├── encounters/

│   │   ├── combat/    

│   │   ├── dialog/    

│   └── notes/

│   └── rosters/

├── themes

│   ├── dark_parchment

│   ├── gm-modern

│   └── rpg-retro

├── main.py

├── gm_ui.py

├── trackeroverlay.py

├── config.json

├── dialog_meta.json

├── dialog.txt

└── README.md



---

## Installation
**Requirements**
- OBS
- Python **3.10+**

**Packages**
```bash
pip install pygame pillow PySide6 markdown
```

## Running the App

Start EncounterOS in the command terminal:

```bash
python gm_ui.py
```

Click Launch Overlay to start the player view. This program can be read
with a window capture in OBS, provided you are using Windows 10/11 (1903 and up)
in your capture properties.

### Themes
Themes live in themes/<theme-name>/theme.json and control:
- Grid/layout regions (e.g., right column, dialog box)
- Colors (card background, borders, text, HP colors, dialog box)
- Font family/sizes
Switch themes in GM UI → Themes (this updates config.json and the overlay re-reads it).

## License & Credits
Icons: Modified from game-icons.net.
Code: Apache 2.0
