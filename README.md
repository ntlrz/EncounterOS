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
- Add/remove characters with optional portrait icons (auto‑sized, grayscale).
- Track HP with quick ± buttons.
- Combat toggle (Peace ↔ Combat):
  - Prompts for missing initiatives.
  - Auto‑rolls (d20 + initMod) if blank.
  - Sorts and assigns turn order.
- Manual initiative entry supported.
- Status Effects via compact popup.
- Launch / Stop the overlay.

### Overlay (Player View)
- Chroma‑key friendly magenta background.
- Right‑side character cards with portrait, HP bar, and status badges.
- Peace: enemies hidden. Combat: enemies show condition text.
- Dialogue box (reads `dialog.txt`, paragraph‑wrapped).

---

## Hotkeys & Shortcuts

### A) When the Overlay Window is Focused
→ Next turn
← Previous turn
↓ Next dialogue line
↑ Previous dialogue line
*Tip:* In OBS, you can click the overlay capture to focus it briefly if needed.

### B) Background Control with AutoHotkey (Optional)
If you use the included **AHK v2** script, you can map **F13–F22** to actions without changing focus.

Default mapping:
- **F14 / F15** → Next / Previous turn  
- **F20 / F21** → Next / Previous dialogue line  
- **F13** → Toggle Combat (C)  
- **F16 / F17 / F18 / F19** → HP adjustments (`=`, `-`, `]`, `[`) if mapped in GM UI

---

## File Structure
├── icons

│   ├── /status/

│   └── /dialog-portraits/

├── themes

│   ├── dark_parchment

│   ├── gm-modern

│   └── rpg-retro

├── gm_ui.py

├── trackeroverlay.py

├── config.json

├── dialog.txt

└── README.md



---

## Installation
**Requirements**
- OBS
- Python **3.10+**

**Packages**
```bash
pip install pygame pillow PySide6
```

##Running the App

Start EncounterOS in the command terminal:

```bash
python gm_ui.py
```

Click Launch Overlay to start the player view. This program can be read
with a window capture in OBS.

### Themes
Stored in themes/<theme-name>/

Each theme contains:
theme.json (grid layout, variables)
*.qss (stylesheet)

Switch themes from the Themes UI (or dropdown).

##License & Credits
Icons: Modified from game-icons.net.
Code: Apache 2.0
