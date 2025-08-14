## Hotkeys & Shortcuts

There are two ways to drive the overlay:

### A) Overlay window (default)
These keys work when the **overlay window** (tracker_overlay.py) is focused:
- **Right Arrow** – Next turn
- **Left Arrow** – Previous turn
- **Down Arrow** – Next dialog line
- **Up Arrow** – Previous dialog line

> Tip: In OBS, you can still click the overlay to focus it briefly if you use a separate display capture, or map your Stream Deck to send keys to the overlay window title.

### B) Via AutoHotkey (optional, background control)
If you installed the provided **AutoHotkey v2** script, you can send function keys **F13–F22** and have them forwarded to the right window even when unfocused.

Default mapping (you can change this in the AHK file):
- **F14 / F15** → Right/Left (next/prev turn)
- **F20 / F21** → `.` / `,` (next/prev dialog)
- **F13** → `C` (toggle combat) *if you mapped your AHK to GM UI’s toggle*
- **F16 / F17 / F18 / F19** → `=`, `-`, `]`, `[` (HP nudges) *only if GM UI handles HP keys in your version*

> IMPORTANT: In the **short GM UI build**, turn changes and dialog navigation live in the overlay’s key handler by default. If you want all hotkeys to be handled by GM UI instead (so the overlay just “listens” via JSON), ask for the **GM‑driven hotkeys variant** and we’ll swap key handling into GM UI and sync via `config.json`.


# DnD Party Tracker Overlay (GM UI + Pygame Overlay)

A lightweight GM control panel (Tkinter) that drives a stream-friendly overlay (Pygame) for OBS.  
Shows party health bars, portraits, status effects, and dialog lines; supports combat turn order with initiative.

## Features
- **GM UI (tkinter)**  
  - Add/remove characters with icon processing (auto-sized grayscale).  
  - Track HP; quick +/− buttons.  
  - Toggle **Combat/Peace**; on **Combat ON**: prompt for missing initiatives, auto-roll (d20+initMod) if blank, **sort**, and assign `turnOrder`.  
  - Manual initiative entry per character supported.  
  - Add status effects via compact **Statuses…** popup; shows emoji in the GM table and badges on the overlay.  
  - Launch/Stop the overlay from the GM UI.

- **Overlay (pygame)**  
  - Magenta background for easy chroma key in OBS.  
  - Right-side character cards with portrait, HP bar, and **status badges** on the HP bar.  
  - **Peace**: enemies hidden; **Combat**: enemies show condition (Healthy/Bruised/etc.).  
  - Dialog box at the bottom in Peace (reads `dialog.txt`, paragraph-wrapped).

## Files
- `gm_ui.py` — The control panel.  
- `tracker_overlay.py` — The render window for OBS.  
- `party.json` — Party data (`GM UI` edits this automatically).  
- `config.json` — Global state (combat mode, dialog index, etc.).  
- `dialog.txt` — Optional lines for the overlay dialog box (blank line separates entries).  
- `icons/` — Character portraits (auto-created).  
- `icons/status/` — 24×24 PNG badges for status keys (optional).

## Install
- Python 3.10+  
- `pip install pygame pillow`
- Windows users: set OBS chroma key color to **magenta** (255, 0, 255).

## Run
1. `python gm_ui.py` (use this to manage everything)
2. Click **Launch Overlay** to start the Pygame window for OBS.

## Workflow
- Add characters in GM UI (choose an optional icon).  
- Set **Init Mod** during creation (or edit later).  
- Toggle **Combat ON** → GM UI fills/collects initiatives, sorts, writes `turnOrder`.  
- Overlay updates automatically by reading `party.json`/`config.json`.

## Status Effects
- In GM UI: click **Statuses…** to toggle effects for the selected character.  
- Overlay draws small badges on the HP bar.  
  - Place PNGs in `icons/status/` named like `poisoned.png`, `stunned.png`, etc.  
  - If a file is missing, a fallback letter badge is shown.

## OBS Tips
- Add a **Game Capture** for the overlay window or a **Window Capture**.  
- Apply **Chroma Key** (color: magenta) to remove negative space.  
- Keep overlay window aspect ratio; it’s resizable.

## Hotkeys / Stream Deck
- Use AutoHotkey (optional) to send hotkeys to GM UI in the background (e.g., toggle combat, next turn).  
- Stream Deck can trigger AHK hotkeys (F13–F22) to control GM UI without focusing it.

## Common Gotchas
- If you see a tiny extra “tk” window, make sure only `gm_ui.py` creates the Tk root, and the overlay is launched as a separate process.  
- If icons don’t appear, confirm the paths in `party.json` and that files exist in `icons/`.  
- For status badges, ensure your PNGs are in `icons/status/` and sized ~24×24 (larger is fine; they auto-scale).

## Roadmap Ideas
- Round counter and effects with auto-expiry.  
- Per‑party presets and multi‑encounter management.  
- Stream Deck profile export.
